"""Database helpers — Supabase URL resolution + connection context manager."""

import os
from contextlib import contextmanager

import psycopg2

_SUPABASE_URL = None


def _supabase_url():
    """Atma Postgres URL from ATMA_DATABASE_URL (loaded by omni-svc from ~/.config)."""
    global _SUPABASE_URL
    if _SUPABASE_URL is None:
        _SUPABASE_URL = os.environ.get("ATMA_DATABASE_URL") or None
    return _SUPABASE_URL

@contextmanager
def get_db():
    """Yield a psycopg2 connection.  Caller MUST consume inside a `with` block."""
    url = _supabase_url()
    if not url:
        raise RuntimeError("no supabase url")
    con = psycopg2.connect(url, connect_timeout=8)
    try:
        yield con
    finally:
        con.close()