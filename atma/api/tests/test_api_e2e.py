"""Atma's API end to end on a real database: create a task, complete it, see the points land."""
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client(clean_db):
    from fastapi.testclient import TestClient
    import main as main_mod
    import utils.tags as tags_mod
    from utils import auth as auth_mod
    os.environ["ATMA_AGENT_TOKEN"] = "e2e-token"
    auth_mod.load_agent_registry.cache_clear()
    no_llm = MagicMock(side_effect=RuntimeError("no LLM in tests"))
    with patch.object(tags_mod, "TAGGING_PROVIDERS", [("none", no_llm)]):
        yield TestClient(main_mod.app), {"Authorization": "Bearer e2e-token"}


def test_a_task_goes_from_created_to_completed_with_points(client, clean_db):
    http, auth = client
    r = http.post("/api/tasks", json={"title": "Learn the hiragana alphabet", "category": "mental",
                                      "priority": 4, "assigned_to": "Me"}, headers=auth)
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["title"] == "Learn the hiragana alphabet"
    assert clean_db.table("tasks").select("assigned_to").eq("id", task["id"]).execute().data == [{"assigned_to": 1}]

    listed = http.get("/api/tasks", headers=auth)
    assert listed.status_code == 200 and [t["id"] for t in listed.json()] == [task["id"]]

    done = http.post(f"/api/tasks/{task['id']}/complete", json={}, headers=auth)
    assert done.status_code == 200, done.text
    rows = clean_db.table("task_completions").select("task_id, points").execute().data
    assert len(rows) == 1 and rows[0]["task_id"] == task["id"] and rows[0]["points"] > 0

    completed = http.get("/api/completed", headers=auth)
    assert completed.status_code == 200, completed.text
    assert completed.json()[0]["task_title"] == "Learn the hiragana alphabet"

    assert http.get("/api/summary/domains", headers=auth).status_code == 200
    assert http.get("/api/skill-tree", headers=auth).status_code == 200


def test_writes_need_a_token(client):
    http, _ = client
    assert http.post("/api/tasks", json={"title": "x", "category": "mental"}).status_code in (401, 403)
