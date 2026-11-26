"""utils.db against a real Postgres: the query builder must behave like the PostgREST client it replaced."""
import pytest

from utils.db import Database


def _task(db, **kw):
    row = {"title": "t", "category": "mental", "priority": 3, **kw}
    return db.table("tasks").insert(row).execute().data[0]


def test_insert_returns_the_row_with_defaults_and_iso_timestamps(clean_db):
    row = _task(clean_db, title="learn hiragana")
    assert row["id"] == 1 and row["title"] == "learn hiragana" and row["is_active"] is True
    assert isinstance(row["created_at"], str) and "T" in row["created_at"]


def test_select_filters_order_and_range(clean_db):
    for i in range(5):
        _task(clean_db, title=f"t{i}", priority=i % 3 + 1, is_active=i != 2)
    t = clean_db.table("tasks")
    assert [r["title"] for r in t.select("title").eq("is_active", True).order("id").execute().data] == ["t0", "t1", "t3", "t4"]
    assert [r["id"] for r in clean_db.table("tasks").select("id").in_("id", [2, 4]).order("id").execute().data] == [2, 4]
    assert [r["id"] for r in clean_db.table("tasks").select("id").order("id", desc=True).range(1, 2).execute().data] == [4, 3]
    assert len(clean_db.table("tasks").select("*").gte("priority", 2).lte("priority", 2).execute().data) == 2
    assert clean_db.table("tasks").select("id").is_("due_date", "null").limit(1).execute().data == [{"id": 1}]


def test_update_and_delete_return_rows_and_refuse_to_run_unfiltered(clean_db):
    _task(clean_db)
    assert clean_db.table("tasks").update({"title": "renamed"}).eq("id", 1).execute().data[0]["title"] == "renamed"
    assert clean_db.table("tasks").update({"title": "x"}).eq("id", 99).execute().data == []
    with pytest.raises(ValueError, match="every row"):
        clean_db.table("tasks").update({"title": "x"}).build()
    with pytest.raises(ValueError, match="every row"):
        clean_db.table("tasks").delete().build()
    assert [r["id"] for r in clean_db.table("tasks").delete().eq("id", 1).execute().data] == [1]


def test_json_columns_round_trip_dicts_and_lists(clean_db):
    spec = {"type": "git_commit", "repos": ["~/omni"], "min": 1}
    task = _task(clean_db, verification=spec)
    assert task["verification"] == spec
    v = clean_db.table("verifications").insert({
        "task_id": task["id"], "questions": [{"q": "a?"}, {"q": "b?"}], "submissions": [],
    }).execute().data[0]
    assert v["questions"] == [{"q": "a?"}, {"q": "b?"}] and v["submissions"] == []
    assert v["state"] == "in_progress"


def test_identifiers_are_validated_and_embedded_resources_rejected(clean_db):
    with pytest.raises(ValueError):
        clean_db.table("tasks; drop table users").select("*").build()
    with pytest.raises(ValueError):
        clean_db.table("tasks").select("id").eq("id = 1 or 1", 1).build()
    with pytest.raises(ValueError, match="embedded"):
        clean_db.table("task_completions").select("*, tasks(title)")


def test_a_failing_statement_rolls_back_its_transaction(clean_db):
    _task(clean_db)
    with pytest.raises(Exception):
        with clean_db.cursor() as cur:
            cur.execute("update tasks set title = 'half' where id = 1")
            cur.execute("select * from no_such_table")
    assert clean_db.table("tasks").select("title").eq("id", 1).execute().data[0]["title"] == "t"


def test_no_database_url_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ATMA_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="ATMA_DATABASE_URL"):
        Database().url()
