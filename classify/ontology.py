"""Ontology loading and access.

The Omni taxonomy — six realms + bound agents — is CONFIG-DRIVEN: it lives in
``omni_ontology.yaml`` and is loaded here. Add a realm or agent there and the
classifier's label space widens with zero code change.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import yaml

_HERE = os.path.dirname(__file__)
# This machine's ontology (instance branch) when present, else the base example: Atma only.
DEFAULT_ONTOLOGY = (os.path.join(_HERE, "omni_ontology.yaml")
                    if os.path.exists(os.path.join(_HERE, "omni_ontology.yaml"))
                    else os.path.join(_HERE, "omni_ontology.example.yaml"))


def load_ontology(path: Optional[str] = None) -> Dict[str, Any]:
    """Load the ontology YAML; ``path`` defaults to the bundled file."""
    p = path or DEFAULT_ONTOLOGY
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Ontology:
    """Typed access to the realms + agents declared in the ontology config."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.data = load_ontology(path)

    @property
    def realms(self) -> Dict[str, Any]:
        return self.data.get("realms", {})

    @property
    def agents(self) -> Dict[str, Any]:
        return self.data.get("agents", {})

    def realm(self, name: str) -> Dict[str, Any]:
        return self.realms[name]

    def agent(self, name: str) -> Dict[str, Any]:
        return self.agents[name]
