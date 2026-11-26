"""Omni classification — reusable "where does this lie in Omni terms" layer.

Public API:
    OmniClassifier     — classify(text) -> OmniClassification (the engine)
    OmniClassification — typed result (realm scores, primary realm, agent)
    JevClient          — fail-open transport (usually constructed implicitly)
    Ontology           — config-driven taxonomy access (realms + agents)
"""

from .classifier import OmniClassifier
from .jev_client import JevClient
from .ontology import Ontology, load_ontology
from .schema import OmniClassification

__all__ = [
    "JevClient",
    "OmniClassification",
    "OmniClassifier",
    "Ontology",
    "load_ontology",
]
