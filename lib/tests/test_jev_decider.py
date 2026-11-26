"""omnikit.jev_decider — Decision / JevDecider over a stub client (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omnikit.jev import JevClient  # noqa: E402
from omnikit.jev_decider import Decision, JevDecider  # noqa: E402


class Stub:
    enabled = True

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def decide(self, state, questions):
        self.calls.append(questions)
        return self.answers


def test_choice_uses_jev_distribution():
    d = JevDecider(Stub({"x": {"probabilities": {"a": 3, "b": 1}, "confidence": 0.95}}))
    out = d.choice("s", {"a": "A", "b": "B"})
    assert out.source == "jev" and out.available and out.argmax == "a" and out.prob("a") == 0.75
    assert out.confident(0.9)


def test_choice_falls_back_to_uniform_when_jev_down():
    out = JevDecider(Stub(None)).choice("s", {"a": "A", "b": "B"})
    assert out.source == "fallback" and not out.available and out.distribution == {"a": 0.5, "b": 0.5}


def test_noul_and_score():
    d = JevDecider(Stub({"x": {"noul": 0.8, "probabilities": {"0": 0.2, "1": 0.8}}}))
    assert d.noul("s", "is it?").prob("true") == 0.8
    assert d.score("s", ["low", "high"], "how much").argmax == "high"
    assert JevDecider(Stub(None)).noul("s", "is it?", fallback=0.3).prob("true") == 0.3


def test_default_client_is_overridable():
    class Mine(JevDecider):
        @staticmethod
        def default_client():
            return Stub(None)

    assert isinstance(Mine().client, Stub)
    assert isinstance(JevDecider().client, JevClient)


def test_decision_helpers():
    dec = Decision({"a": 1, "b": 1})
    assert round(dec.entropy(), 6) == 1.0 and dec.expectation({"a": 10, "b": 0}) == 5.0
    assert dec.top_k(1)[0][1] == 0.5 and dec.sample() in ("a", "b")
