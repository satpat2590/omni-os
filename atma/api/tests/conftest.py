"""Atma's tests and the database they run against.

Tests that touch Postgres take the `atma_db` fixture: a brand-new database created for this test
session on ATMA_TEST_SERVER_URL, built from nothing by scripts/migrate.py, and dropped at the end.
Each test that writes takes `clean_db`, which empties every table first and seeds user 1.

    ATMA_TEST_SERVER_URL="postgresql:///postgres?host=$HOME/pgdata&port=5434"   # the omnidev cluster

Without ATMA_TEST_SERVER_URL those tests skip. The server must be local (a socket or localhost):
the fixture refuses anything else, so a test run can never reach a production database.
"""
import io
import os
import sys
import uuid

import pytest

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, API_DIR)
sys.path.insert(0, os.path.join(API_DIR, "scripts"))

SERVER = os.environ.get("ATMA_TEST_SERVER_URL")


def _local_only(url: str) -> dict:
    from psycopg2.extensions import parse_dsn
    parts = parse_dsn(url)
    host = parts.get("host", "")
    if host and not (host.startswith("/") or host in ("localhost", "127.0.0.1", "::1")):
        raise pytest.UsageError(f"ATMA_TEST_SERVER_URL must be a local server, not host {host!r}")
    return parts


def _admin(parts: dict):
    import psycopg2
    from psycopg2.extensions import make_dsn
    con = psycopg2.connect(make_dsn(**parts))
    con.autocommit = True
    return con


@pytest.fixture(scope="session")
def make_database():
    """Create empty, uniquely named databases on the test server; drop them all at the end."""
    if not SERVER:
        pytest.skip("ATMA_TEST_SERVER_URL is not set: no local Postgres to test against")
    from psycopg2.extensions import make_dsn
    parts = _local_only(SERVER)
    admin = _admin(parts)
    made = []

    def create() -> str:
        name = f"atma_test_{uuid.uuid4().hex[:10]}"
        with admin.cursor() as cur:
            cur.execute(f'create database "{name}"')
        made.append(name)
        return make_dsn(**{**parts, "dbname": name})

    yield create
    from utils.db import db
    db.close()
    with admin.cursor() as cur:
        for name in made:
            cur.execute(f'drop database if exists "{name}" with (force)')
    admin.close()


@pytest.fixture(scope="session")
def atma_db(make_database):
    """A migrated Atma database for the session; ATMA_DATABASE_URL points at it while tests run."""
    from migrate import migrate
    url = make_database()
    migrate(url, out=io.StringIO())
    before = os.environ.get("ATMA_DATABASE_URL")
    os.environ["ATMA_DATABASE_URL"] = url
    yield url
    if before is None:
        os.environ.pop("ATMA_DATABASE_URL", None)
    else:
        os.environ["ATMA_DATABASE_URL"] = before


@pytest.fixture
def clean_db(atma_db):
    """Every Atma table emptied, ids restarted, and the one human user (id 1) seeded."""
    from utils.db import db
    tables = [r["table_name"] for r in db.query(
        "select table_name from information_schema.tables "
        "where table_schema = 'public' and table_type = 'BASE TABLE' and table_name <> 'schema_migrations'")]
    db.query("truncate table " + ", ".join(f'public."{t}"' for t in tables) + " restart identity cascade")
    db.query("insert into users (id, name, user_type) values (1, 'Me', 'human')")
    db.query("select setval('users_id_seq', 1, true)")
    return db
