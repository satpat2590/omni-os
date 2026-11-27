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
            assert self.headers["Authorization"] == "Bearer test-dummy"
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
            monkeypatch.setenv("OMNI_AI_PROVIDER","compatible")
            monkeypatch.setenv("OMNI_AI_KEY","test-dummy")
            monkeypatch.setenv("OMNI_AI_MODEL","test-model")
            monkeypatch.setenv("OMNI_AI_BASE_URL",f"http://127.0.0.1:{server.server_port}/v1")
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


@pytest.mark.parametrize("title,category,path", [
    ("Do three sets of squats at the gym","physical",["Strength Training","Squats"]),
    ("Practice Python algorithms","mental",["Computer Science"]),
    ("Going to the Gym","physical",["Movement"]),
    ("Practice Hiragana Alphabet","mental",["Languages","Japanese","Hiragana"]),
    ("Practice writing katakana","mental",["Languages","Japanese","Katakana"]),
    ("Review hiragana and katakana","mental",["Languages","Japanese"]),
    ("Practice Japanese","mental",["Languages","Japanese"]),
    ("Practice French and Spanish","mental",["Languages"]),
    ("Pay rent","financial",["Bills"]),
    ("Catch up with a friend","social",["Relationships"]),
    ("Prepare for tomorrow","unclassified",[]),
])
def test_catalog_capture(owner,title,category,path):
    row = owner.post("/api/tasks",json={"title":title}).json()
    assert row["category"] == category
    assert row["classification"]["path"] == path


def test_refine_old_languages_link_after_base_moved(owner,clean_db):
    from utils.daily import run, tag_paths
    task = owner.post("/api/tasks",json={
        "title":"Practice a language","description":"Review flashcards"
    }).json()
    base = task["classification"]["tag_id"]
    new_parent = clean_db.query("insert into tags(name,category) values ('Skills','mental') returning id")[0]["id"]
    governance.move(base,new_parent)
    clean_db.query("""update tasks set description='Review Hiragana flashcards',
        classification=classification || '{"catalog_revision":1,"input_description":"Review Hiragana flashcards"}'
        where id=%s""",(task["id"],))
    assert run()["classified"] == 1
    leaf = clean_db.query("select tag_id from task_tags where task_id=%s",(task["id"],))[0]["tag_id"]
    assert next(t["path"] for t in tag_paths() if t["id"] == leaf) == ["Skills","Languages","Japanese","Hiragana"]
    again = owner.post("/api/tasks",json={"title":"Practice ひらがな"}).json()
    assert again["classification"]["tag_id"] == leaf
    assert run()["classified"] == 0


def test_provider_selects_deep_catalog_path(owner,clean_db):
    from utils.daily import run, tag_paths
    task = owner.post("/api/tasks",json={"title":"Review yesterday's flashcards"}).json()
    path = ["Languages","Japanese","Kanji"]
    def choose(messages):
        assert path in json.loads(messages[-1]["content"])["catalog"]["mental"]
        return json.dumps({"category":"mental","path":path})
    assert run(choose,"test-model")["classified"] == 1
    tag = clean_db.query("select tag_id from task_tags where task_id=%s",(task["id"],))[0]["tag_id"]
    assert next(t["path"] for t in tag_paths() if t["id"] == tag) == path


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


def test_endpoint_credentials_are_bound_to_destination(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]/"scripts"))
    import classifier
    monkeypatch.setattr(classifier,"CONFIG",tmp_path/"settings")
    monkeypatch.setattr(classifier,"REPORT",tmp_path/"report")
    settings = dict(classifier.DEFAULT,mode="compatible",model="example",key="test-only")
    classifier.configure(settings)
    assert classifier.CONFIG.stat().st_mode & 0o777 == 0o600
    assert classifier.public()["hasKey"] and "key" not in classifier.public()
    classifier.configure(dict(settings,key="",model="cheaper-model"))
    assert classifier.config()["key"] == "test-only"
    classifier.configure(dict(settings,key="",endpoint="https://models.example/v1"))
    assert not classifier.public()["hasKey"]
    with pytest.raises(ValueError):
        classifier.configure(dict(settings,endpoint="http://models.example/v1"))


def test_existing_catalog_id_reused(owner,clean_db):
    from utils.daily import run
    known = owner.post("/api/tasks",json={"title":"Practice guitar"}).json()
    task = owner.post("/api/tasks",json={"title":"Rehearse the new arrangement"}).json()
    assert task["category"] == "unclassified"
    tag = known["classification"]["tag_id"]
    assert run(lambda _:json.dumps({"existing":tag}),"model")["classified"] == 1
    assert clean_db.query("select tag_id from task_tags where task_id=%s",(task["id"],)) == [{"tag_id":tag}]
