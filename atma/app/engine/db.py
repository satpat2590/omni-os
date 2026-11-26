"""Supabase connection seam for the engine.

Single source of truth for "how do we reach the Atma Postgres": the
ATMA_DATABASE_URL env var, which omni-svc loads from ~/.config. No .env or
shell-rc fallbacks: a secret has one home.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg2

_url_cache: str | None = None


def supabase_url() -> str | None:
    """The Atma Postgres URL from ATMA_DATABASE_URL (loaded by omni-svc), cached across calls."""
    global _url_cache
    if _url_cache is None:
        _url_cache = os.environ.get("ATMA_DATABASE_URL") or None
    return _url_cache

@contextmanager
def connect() -> Iterator[psycopg2.extensions.connection]:
    """Yield a psycopg2 connection.  Must be used inside a ``with`` block."""
    url = supabase_url()
    if not url:
        raise RuntimeError("no Supabase URL resolved (set ATMA_DATABASE_URL)")
    con = psycopg2.connect(url, connect_timeout=8)
    try:
        yield con
    finally:
        con.close()
