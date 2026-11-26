"""System page: services, plans and job status, generated from the Omni core registry.

    GET /system        the page (static/system.html)
    GET /api/system    the data behind it: service states, plans as Mermaid, every job's status

Access control is not done here. The dashboard wears ``TunnelGuard`` (server.py), which requires
the key for every request that arrives through the Cloudflare tunnel, so these routes are covered
like every other route.
"""
import sys
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "core"))

from omni_core import diagram, jobstate, readiness, status  # noqa: E402
from omni_core.ledger import Ledger, LedgerError  # noqa: E402
from omni_core.registry import load  # noqa: E402

CACHE_S = 30          # one snapshot costs ~50 launchctl calls; serve it for this long

router = APIRouter()
_cache = {"at": 0.0, "data": None}


def build_snapshot() -> dict:
    registry = load()
    note = None
    try:
        last_runs = Ledger().last_runs()
    except LedgerError as exc:
        last_runs, note = {}, f"run ledger unavailable: {exc}"
    states, services = jobstate.job_states(registry, last_runs=last_runs), status.service_states(registry)
    data = diagram.snapshot(registry, states, services)
    data["note"] = note
    data["readiness"] = _readiness(registry, states, services)
    return data


def _readiness(registry, states, services):
    try:
        runs = Ledger().runs_since(24)
    except LedgerError:
        runs = []
    verdict = readiness.evaluate(registry, states=states, services=services, runs_24h=runs)
    return {"ready": verdict.ready, "passed": sum(c.ok for c in verdict.checks), "total": len(verdict.checks),
            "failing": [{"area": c.area, "name": c.name, "detail": c.detail} for c in verdict.failures()]}


@router.get("/system")
def system_page():
    return FileResponse(HERE / "static" / "system.html")


@router.get("/api/system")
def system_api():
    now = time.time()
    if _cache["data"] is None or now - _cache["at"] > CACHE_S:
        _cache["data"], _cache["at"] = build_snapshot(), now
    return _cache["data"]
