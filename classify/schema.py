"""Result schema for Omni classification.

``OmniClassification`` is the single typed return value of an ``OmniClassifier``
call. It is fail-open: ``available`` is True only when Jev actually answered;
otherwise ``source`` explains why not (``disabled`` / ``error`` / ``empty`` /
``keyword`` / ``none``), so callers never branch on ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OmniClassification:
    """Calibrated result of classifying one input against the Omni ontology."""

    available: bool = False
    # "jev" | "disabled" | "error" | "empty" | "keyword" | "none"
    source: str = "disabled"

    # multi-label realm relevance (independent noul probes; do NOT sum to 1)
    realm_scores: Dict[str, float] = field(default_factory=dict)
    # single-label primary realm (choice) + distribution + confidence
    primary_realm: Optional[str] = None
    primary_realm_probabilities: Dict[str, float] = field(default_factory=dict)
    primary_realm_confidence: Optional[float] = None
    # multi-label agent ownership (independent noul probes)
    agent_scores: Dict[str, float] = field(default_factory=dict)

    # raw Jev answers, for callers that layered extra questions of their own
    raw: Dict[str, Any] = field(default_factory=dict)

    # ---- helpers ----
    def top_realm(self, min_score: float = 0.35) -> Optional[str]:
        """Highest-scoring realm, or None if nothing clears the bar."""
        if not self.realm_scores:
            return None
        best = max(self.realm_scores, key=lambda k: self.realm_scores[k])
        return best if self.realm_scores[best] >= min_score else None

    def secondary_realms(self, threshold: float = 0.2, exclude_primary: bool = True) -> List[str]:
        """Other realms with meaningful mass (multi-label read)."""
        realms = []
        for name, score in sorted(self.realm_scores.items(), key=lambda kv: -kv[1]):
            if score < threshold:
                break
            if exclude_primary and name == self.primary_realm:
                continue
            realms.append(name)
        return realms

    def responsible_agent(self, min_score: float = 0.35) -> Optional[str]:
        """Highest-scoring agent, or None if nothing clears the bar."""
        if not self.agent_scores:
            return None
        best = max(self.agent_scores, key=lambda k: self.agent_scores[k])
        return best if self.agent_scores[best] >= min_score else None

    def realm_confident(self, threshold: float = 0.6) -> bool:
        """True when Jev answered and the primary-realm choice is confident."""
        return bool(
            self.available
            and self.primary_realm_confidence is not None
            and self.primary_realm_confidence >= threshold
        )

    def summary(self) -> str:
        """One-line human-readable read of the classification."""
        if not self.available:
            return f"<{self.source}>"
        realms = ", ".join(f"{k} {v:.2f}" for k, v in sorted(self.realm_scores.items(), key=lambda kv: -kv[1]))
        agent = self.responsible_agent() or "—"
        return f"primary={self.primary_realm} (conf {self.primary_realm_confidence}) | realms: {realms} | agent: {agent}"
