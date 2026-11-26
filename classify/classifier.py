"""Omni classification — the classification logic (questions → Jev → typed result).

This is the engine that turns raw text into an ``OmniClassification``. The
transport (``jev_client``), the result type (``schema``), and the taxonomy
(``ontology``) live in their own modules so each concern changes independently.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .jev_client import JevClient
from .ontology import Ontology
from .schema import OmniClassification


class OmniClassifier:
    """Classify arbitrary text against the Omni ontology (realms + agents)."""

    def __init__(self, ontology_path: Optional[str] = None, client: Optional[JevClient] = None) -> None:
        self.ontology = Ontology(ontology_path)
        self.realms: Dict[str, Any] = self.ontology.realms
        self.agents: Dict[str, Any] = self.ontology.agents
        self.client = client or JevClient()

    @property
    def enabled(self) -> bool:
        return bool(self.client.enabled)

    # ---- deterministic floor (works with Jev down) ----
    def keyword_classify(self, text: str) -> OmniClassification:
        """Deterministic keyword floor; never needs the network or a key."""
        t = (text or "").lower()
        scores: Dict[str, float] = {}
        for name, realm in self.realms.items():
            hits = sum(1 for kw in realm.get("keywords", []) if kw in t)
            scores[name] = round(min(hits / 3.0, 1.0), 3)  # saturate at 3 hits
        any_hit = any(scores.values())
        return OmniClassification(
            available=False,
            source="keyword" if any_hit else "none",
            realm_scores=scores if any_hit else {},
        )

    # ---- question builder ----
    def build_questions(self, extra_questions: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
        """One fan-out set: realm probes + primary choice + agent probes (+ extras)."""
        q: Dict[str, Dict[str, Any]] = {}
        for name, realm in self.realms.items():
            agents = ", ".join(realm.get("agents") or ["(none)"])
            q[f"realm_{name}"] = {
                "type": "noul",
                "instructions": (
                    f"Does this input concern the {name} realm ({realm['meaning']})? "
                    f"{realm.get('description', '')} Bound agents: {agents}."
                ),
            }
        criteria = {
            name: f"{realm['meaning']} — {realm.get('description', '')[:100]}"
            for name, realm in self.realms.items()
        }
        criteria["uncertain"] = "None of the above / ambiguous / cross-cutting"
        q["primary_realm"] = {
            "type": "choice",
            "instructions": "Which single realm is this input PRIMARILY about?",
            "criteria": criteria,
        }
        for name, agent in self.agents.items():
            q[f"agent_{name}"] = {
                "type": "noul",
                "instructions": (
                    f"Is agent {name} ({agent.get('role', '')}, realm {agent.get('realm', '')}) "
                    "the one responsible for acting on this input?"
                ),
            }
        if extra_questions:
            q.update(extra_questions)
        return q

    @staticmethod
    def render_state(text: str, title: Optional[str] = None, body_limit: int = 3000) -> Any:
        """Build the compact state Jev evaluates (raw evidence, not a pre-label)."""
        body = (text or "").strip()[:body_limit]
        if title:
            return {"title": title.strip(), "body": body}
        return body

    # ---- main ----
    def classify(
        self,
        text: str,
        title: Optional[str] = None,
        extra_questions: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> OmniClassification:
        """Classify ``text`` against the Omni ontology. Never raises.

        Returns ``available=False`` (with a ``source``) when Jev is disabled or
        errors, so callers degrade to ``keyword_classify`` or their own floor.
        """
        if not text or not text.strip():
            return OmniClassification(available=False, source="empty")
        if not self.enabled:
            return OmniClassification(available=False, source="disabled")
        state = self.render_state(text, title)
        questions = self.build_questions(extra_questions)
        answers = self.client.decide(state, questions)
        if answers is None:
            return OmniClassification(available=False, source="error")
        return self.from_answers(answers)

    def from_answers(self, answers: Dict[str, Any]) -> OmniClassification:
        """Parse the raw Jev ``answers`` dict into a typed ``OmniClassification``."""
        res = OmniClassification(available=True, source="jev", raw=answers)
        for name in self.realms:
            a = answers.get(f"realm_{name}")
            if isinstance(a, dict) and a.get("noul") is not None:
                res.realm_scores[name] = round(float(a["noul"]), 3)
        pr = answers.get("primary_realm")
        if isinstance(pr, dict):
            res.primary_realm = pr.get("choice")
            probs = pr.get("probabilities")
            if isinstance(probs, dict):
                res.primary_realm_probabilities = {str(k): float(v) for k, v in probs.items()}
            if pr.get("confidence") is not None:
                res.primary_realm_confidence = round(float(pr["confidence"]), 3)
        for name in self.agents:
            a = answers.get(f"agent_{name}")
            if isinstance(a, dict) and a.get("noul") is not None:
                res.agent_scores[name] = round(float(a["noul"]), 3)
        return res
