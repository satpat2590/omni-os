from app.db import get_db, _supabase_url
from app.helpers import _parse_lesson_title, _score_color, build_lesson_index
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, FileResponse
import json, os, re, sqlite3, subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from app.settings import OBSIDIAN_CURRICULUM, OBSIDIAN_DAILY, WHOOP_DB, SHIP_REPO

router = APIRouter()
ALIGNMENT_DIR = OBSIDIAN_CURRICULUM / "alignment-reports"
# The Atma tree, written nightly by ~/omni/mindmap.py to the Omni root's static/.
GRAPH_JSON = Path(__file__).resolve().parents[3] / "static" / "graph.json"
STATIC = Path(__file__).parent.parent / "static"

# mindmap_data (570-575) — keep this one, remove the duplicate at 946-950
@router.get("/api/mindmap")
def mindmap_data():
    """Serve pre-generated graph.json."""
    if GRAPH_JSON.exists():
        return FileResponse(GRAPH_JSON)
    return JSONResponse({"error": "graph not generated"}, status_code=503)

# health (1049-1056)
@router.get("/api/health")
def health():
    """Service health check."""
    return {
        "status": "ok",
        "service": "atma-dashboard",
        "version": "1.0.0",
    }

# index (1061-1063)
@router.get("/")
def index():
    return FileResponse(STATIC / "index.html")

# mindmap_page (1066-1068)
@router.get("/mindmap")
def mindmap_page():
    return FileResponse(STATIC / "mindmap.html")

@router.get("/gyani")
def gyani_page():
    return FileResponse(STATIC / "gyani.html")