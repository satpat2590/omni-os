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
            from utils.daily import run
            from omnikit.providers import complete
            unknown = owner.post("/api/tasks",json={"title":"Prepare for tomorrow"}).json()
            assert unknown["category"] == "unclassified"
            server.answer = '{"category":"mental","base":"Music","leaf":"Harmony"}'
            result = run(complete,"test-model")
            assert result["classified"] == result["calls"] == 1
            assert run(complete,"test-model")["calls"] == 0
            owner.post("/api/tasks",json={"title":"Figure things out"})
            server.answer = "malformed"
            assert run(complete,"test-model")["errors"] == 1
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("title,category,tag", [
    ("Do three sets of squats at the gym","physical","Strength Training"),
    ("Practice Python algorithms","mental","Computer Science"),
    ("Pay rent","financial","Bills"),
    ("Catch up with a friend","social","Relationships"),
    ("Prepare for tomorrow","unclassified",None),
])
def test_catalog_capture(owner,title,category,tag):
    row = owner.post("/api/tasks",json={"title":title}).json()
    assert row["category"] == category
    assert row["classification"]["path"] == ([tag] if tag else [])


def test_old_fallback_and_changed_title(owner,clean_db):
    from utils.daily import run
    task = owner.post("/api/tasks",json={"title":"Read a book"}).json()
    tid = task["id"]
    clean_db.query("""update tasks set title='Lift weights', classification=
        jsonb_build_object('policy_version',1,'method','default','tag_id',%s::int) where id=%s""",
        (task["classification"]["tag_id"],tid))
    assert run()["classified"] == 1
    assert clean_db.query("select category from tasks where id=%s",(tid,))[0]["category"] == "physical"
    clean_db.query("update tasks set title='Pay rent' where id=%s",(tid,))
    assert run()["classified"] == 1
    assert clean_db.query("select category from tasks where id=%s",(tid,))[0]["category"] == "financial"


def test_model_budget_and_manual_links(owner,clean_db):
    from utils.daily import run
    for title in ("Prepare tomorrow","Think ahead","Try something new"):
        owner.post("/api/tasks",json={"title":title})
    answer = lambda _: '{"category":"social","base":"Community"}'
    assert run(answer,"example",1)["calls"] == 1
    assert run(answer,"example",1)["classified"] == 1
    unmatched = clean_db.query("select id from tasks where category='unclassified'")[0]["id"]
    tag = clean_db.query("select id from tags limit 1")[0]["id"]
    clean_db.query("insert into task_tags(task_id,tag_id) values (%s,%s)",(unmatched,tag))
    result = run(answer,"example",1)
    assert result["skipped"] == 1 and result["calls"] == 0
    assert clean_db.query("select tag_id from task_tags where task_id=%s",(unmatched,)) == [{"tag_id":tag}]
