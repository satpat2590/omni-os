"""Tests for the Omni classification layer — offline (mocked) + fail-open paths."""

import json
import os
import sys
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classify import JevClient, OmniClassifier  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixture_ontology.yaml")
REALMS = ["edoras", "atma", "soma", "raga", "smriti", "omni"]
AGENTS = ["argus", "paisa", "logistis", "gyani", "veltiosi", "satya"]


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _answers(primary="edoras", edoras=0.8, agent="argus"):
    realms = {name: {"noul": 0.05} for name in REALMS}
    realms["edoras"] = {"noul": edoras}
    agents = {name: {"noul": 0.05} for name in AGENTS}
    agents[agent] = {"noul": 0.7}
    answers = {f"realm_{k}": v for k, v in realms.items()}
    answers.update({f"agent_{k}": v for k, v in agents.items()})
    answers["primary_realm"] = {
        "type": "choice",
        "choice": primary,
        "probabilities": {primary: 0.9, "uncertain": 0.1},
        "confidence": 0.95,
    }
    return {"answers": answers}


# ---- deterministic floor ----
def test_keyword_floor_hit():
    c = OmniClassifier(ontology_path=FIXTURE)
    r = c.keyword_classify("rebalance the radagast portfolio and run a backtest")
    assert r.source == "keyword" and not r.available
    assert r.realm_scores.get("edoras", 0.0) > 0


def test_keyword_floor_no_match():
    c = OmniClassifier(ontology_path=FIXTURE)
    r = c.keyword_classify("hello there")
    assert r.source == "none" and r.realm_scores == {}


# ---- fail-open / degenerate paths ----
def test_classify_empty():
    c = OmniClassifier(ontology_path=FIXTURE)
    r = c.classify("   ")
    assert r.source == "empty" and not r.available


def test_classify_disabled():
    c = OmniClassifier(ontology_path=FIXTURE, client=JevClient(enabled=False))
    r = c.classify("rebalance portfolio")
    assert r.source == "disabled" and not r.available


def test_classify_transport_error(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    c = OmniClassifier(ontology_path=FIXTURE, client=JevClient(api_key="test-key"))
    r = c.classify("rebalance portfolio")
    assert r.source == "error" and not r.available


def test_classify_malformed_response(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: FakeResp({"no": "answers"}))
    c = OmniClassifier(ontology_path=FIXTURE, client=JevClient(api_key="test-key"))
    r = c.classify("rebalance portfolio")
    assert r.source == "error" and not r.available


# ---- happy path (mocked transport) ----
def test_classify_success(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data.decode())
        return FakeResp(_answers())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = OmniClassifier(ontology_path=FIXTURE, client=JevClient(api_key="test-key"))
    r = c.classify("rebalance the Radagast portfolio")

    assert r.available and r.source == "jev"
    assert r.primary_realm == "edoras"
    assert r.realm_scores["edoras"] > 0.7
    assert r.responsible_agent() == "argus"
    assert r.realm_confident(0.6)

    q = captured["body"]["questions"]
    assert "realm_edoras" in q and "primary_realm" in q and "agent_argus" in q
    assert q["primary_realm"]["type"] == "choice"
    assert q["realm_edoras"]["type"] == "noul"
    assert q["agent_argus"]["type"] == "noul"


def test_extra_questions_merged(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data.decode())
        return FakeResp(_answers())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = OmniClassifier(ontology_path=FIXTURE, client=JevClient(api_key="test-key"))
    c.classify("rebalance portfolio", extra_questions={"goal_stated": {"type": "noul", "instructions": "goal?"}})
    assert "goal_stated" in captured["body"]["questions"]


# ---- live smoke (needs a real key) ----
def _key_available(name):
    if os.environ.get(name, "").strip():
        return True
    try:
        for line in open(os.path.expanduser("~/.hermes/.env")):
            if line.startswith(name + "=") and line.split("=", 1)[1].strip().strip('"').strip("'"):
                return True
    except OSError:
        pass
    return False


@pytest.mark.skipif(not _key_available("TYPESAFE_API_KEY"), reason="no TYPESAFE_API_KEY")
def test_live_smoke():
    c = OmniClassifier(ontology_path=FIXTURE)
    assert c.enabled
    r = c.classify("rebalance the Radagast portfolio to hit its target allocations")
    assert r.available
    assert r.primary_realm == "edoras"
    assert r.realm_scores.get("edoras", 0.0) >= 0.5
