"""Omni OS base dashboard: the system page and the Atma mindmap.

    uvicorn dashboard:app --host 127.0.0.1 --port 8600

A machine with domains of its own runs its own dashboard (on its instance branch) and mounts the
same system router there. This module is what a fresh Omni OS checkout serves.
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

# Every request that arrives through a Cloudflare tunnel needs the key in ~/.config/omni-system.key
# (core/omni_core/tunnel_guard.py). Deliberately not in a try/except: if the guard cannot load, the
# dashboard must fail to start, not start open to the internet.
sys.path.insert(0, str(ROOT / "core"))
from omni_core.tunnel_guard import TunnelGuard  # noqa: E402
from system_page import router as system_router  # noqa: E402

app = FastAPI(title="Omni OS")
app.add_middleware(TunnelGuard)
app.include_router(system_router)


@app.get("/")
def index():
    return RedirectResponse("/system")


@app.get("/mindmap")
def mindmap():
    """The Atma tree, drawn from static/graph.json (written nightly by mindmap.py)."""
    return FileResponse(STATIC / "mindmap.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
