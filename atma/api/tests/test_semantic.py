"""Exercise the installed, pinned models through the daily classifier and a disposable database."""
import json
import os

import pytest

from utils.daily import run
from utils.data import TaskCreate
from utils.governance import create


@pytest.fixture(scope="module")
def local_nlp():
    directory = os.environ.get("ATMA_TEST_NLP_DIR")
    if not directory:
        pytest.skip("Local NLP assets are tested by ./install.sh test")
    from utils.semantic import SemanticClassifier
    return SemanticClassifier(directory)


def test_offline_paraphrases_and_uncertainty(clean_db, local_nlp):
    cases = [
        ("Take a stroll around the block", None, ["Movement", "Walking"]),
        ("Send the landlord this month's payment", None, ["Bills"]),
        ("Give my mother a ring", None, ["Relationships"]),
        ("Going to the gym", "I need to dispute a duplicate charge on my monthly bill.", ["Bills"]),
        ("Don't practice Hiragana Alphabet", None, []),
        ("Watch my cousin lift weights", None, []),
        ("Get it over with", None, []),
    ]
    for title, description, _ in cases:
        create(TaskCreate(title=title, description=description), 1, 1)
    report = run(semantic=local_nlp, mode="offline")
    assert report["calls"] == report["errors"] == 0
    decisions = [r["classification"] for r in clean_db.query("SELECT classification FROM tasks ORDER BY id")]
    for decision, (_, _, path) in zip(decisions, cases, strict=True):
        assert decision["path"] == path
        assert decision["method"] == ("nlp" if path else "needs_context")
    assert run(semantic=local_nlp, mode="offline")["classified"] == 0


def test_hybrid_only_pays_for_uncertain_tasks(clean_db, local_nlp):
    for title in ["Take a stroll around the block", "Follow up on yesterday", "Do it later"]:
        create(TaskCreate(title=title), 1, 1)
    profile = {"currentState":"Starting a new job", "idealState":"Reconnect with old friends"}
    def respond(messages):
        assert "growth_context" not in json.loads(messages[-1]["content"])
        return '{"target":null}'
    stats = run(respond, limit=1, semantic=local_nlp, mode="compatible", profile=profile)
    assert stats["calls"] == stats["classified"] == 1
    assert stats["errors"] == 0
    def shared(messages):
        assert json.loads(messages[-1]["content"])["growth_context"] == profile
        return '{"target":null}'
    stats = run(shared, limit=1, mode="api", profile=profile, share_context=True)
    assert stats["calls"] == 1 and stats["errors"] == 0
    assert clean_db.query("select count(*) as n from tasks where classification->>'method'='nlp'")[0]["n"] == 1


def test_goals_cannot_supply_missing_task_evidence(clean_db, local_nlp, monkeypatch):
    monkeypatch.setattr(local_nlp, "context", ["I spend all my time at my desk", "I want to master the piano"])
    create(TaskCreate(title="Do it later"), 1, 1)
    assert run(semantic=local_nlp, mode="offline")["pending"] == 1
    assert not clean_db.query("select tag_id from task_tags")
