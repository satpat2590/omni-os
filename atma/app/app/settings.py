"""Everything machine-specific about the Atma dashboard, from the environment.

Each machine sets these in ~/.config/omni/*.env (core/bin/omni-svc loads them); atma/README.md lists
them. Unset, every source falls back to a default that simply finds no data, and every optional
integration is off.
"""
import os
from pathlib import Path


def _path(var: str, default: str) -> Path:
    return Path(os.path.expanduser(os.environ.get(var, default)))


# The owner of the tree: the human whose growth this is (users.id).
OWNER_ID = int(os.environ.get("ATMA_OWNER_ID", "1"))

# Evidence and context sources.
VAULT = _path("ATMA_VAULT", "~/Obsidian")
OBSIDIAN_CURRICULUM = VAULT / os.environ.get("ATMA_VAULT_CURRICULUM_DIR", "Curriculum")
OBSIDIAN_DAILY = VAULT / os.environ.get("ATMA_VAULT_DAILY_DIR", "Daily-Notes")
WHOOP_DB = _path("ATMA_WHOOP_DB", "~/.atma/whoop.db")
SHIP_REPOS = [Path(os.path.expanduser(p)) for p in os.environ.get("ATMA_SHIP_REPOS", "~/omni").split(os.pathsep) if p]
SHIP_REPO = SHIP_REPOS[0] if SHIP_REPOS else Path(os.path.expanduser("~/omni"))
SHIP_AUTHOR = os.environ.get("ATMA_SHIP_AUTHOR") or None


def openrouter_key() -> str:
    """The OpenRouter key for Gyani and triage, from the environment only."""
    return os.environ.get("OPENROUTER_API_KEY", "")


# Optional: hand delegated tasks to Hermes's kanban board, so the agent is notified.
HERMES_PYTHON = os.environ.get("ATMA_HERMES_PYTHON") or None          # Hermes's own interpreter
HERMES_KANBAN_PROFILE = os.environ.get("ATMA_HERMES_KANBAN_PROFILE", "default")

# Optional: artifact submissions from a Google Drive folder, through a Google Workspace CLI script.
GWS_SCRIPT = _path("ATMA_GWS_SCRIPT", "") if os.environ.get("ATMA_GWS_SCRIPT") else None
GWS_HOME = os.environ.get("ATMA_GWS_HOME") or None                     # passed to it as HERMES_HOME
SUBMISSIONS_FOLDER = os.environ.get("ATMA_SUBMISSIONS_FOLDER", "Atma-Submissions")
