from concurrent.futures import ThreadPoolExecutor
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest
from fastapi.testclient import TestClient
from main import app
from utils import auth, governance
from utils.data import TaskCreate


@pytest.fixture
def owner(clean_db, monkeypatch):
    monkeypatch.setenv("ATMA_GOVERNANCE", "1")
    monkeypatch.setenv("OMNI_AI_PROVIDER", "offline")
    monkeypatch.setenv("ATMA_AGENT_TOKEN", "owner-test")
    auth.load_agent_registry.cache_clear()
    yield TestClient(app, headers={"Authorization": "Bearer owner-test"})
    auth.load_agent_registry.cache_clear()


def test_title_only_concurrent_creation_and_reparent(owner, clean_db):
    def add(_):
        res = owner.post("/api/agent/tasks", json={"title": "Learn piano"})
        assert res.status_code == 200, res.text
        return res.json()["classification"]["tag_id"]
    with ThreadPoolExecutor(2) as pool:
        tag, same = pool.map(add, range(2))
    assert tag == same
    parent = clean_db.query("insert into tags(name,category) values ('Arts','mental') returning id")[0]["id"]
    move = lambda t,p: owner.patch(f"/api/tags/{t}/parent",json={"parent_tag_id":p})
    assert move(tag,parent).status_code == 200
    assert move(parent,tag).status_code == 409
    assert move(tag,tag).status_code == 409
    assert clean_db.query("select tag_id from task_tags") == [{"tag_id":tag}]*2
    assert add(2) == tag
    assert move(tag,None).status_code == 200


def test_local_provider_and_malformed_output_fallback(owner, monkeypatch):
    class Server(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/v1/chat/completions" and body["model"] == "test-model"
            reply = json.dumps({"choices":[{"message":{"content":self.server.answer}}]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(reply)
    monkeypatch.setattr("socket.getfqdn", lambda *args: "localhost")
    with HTTPServer(("127.0.0.1",0),Server) as server:
        thread = Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            monkeypatch.setenv("OMNI_AI_PROVIDER","local")
            monkeypatch.setenv("OMNI_AI_MODEL","test-model")
            monkeypatch.setenv("OMNI_LOCAL_BASE_URL",f"http://127.0.0.1:{server.server_port}/v1")
            server.answer = '{"category":"mental","path":["Arts","Music"]}'
            task = owner.post("/api/tasks",json={"title":"Learn piano"}).json()
            assert task["classification"]["method"] == "provider"
            server.answer = "malformed"
            assert governance.suggest(TaskCreate(title="Learn piano")) == ("mental",["Learning"],"keyword")
        finally:
            server.shutdown()
            thread.join()
