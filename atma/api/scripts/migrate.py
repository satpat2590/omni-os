#!/usr/bin/env python3
"""Bring an Atma database up to date: apply migrations/NNN_*.sql in order, once each.

    python3 scripts/migrate.py                 # the database in ATMA_DATABASE_URL
    python3 scripts/migrate.py --database-url URL
    python3 scripts/migrate.py --baseline      # an existing Atma database: record 000 as applied
    python3 scripts/migrate.py --status        # list applied and pending, change nothing

Each migration runs in its own transaction and is recorded in public.schema_migrations, so a run
that fails part-way leaves every earlier migration applied and the failed one not.

000_base.sql creates Atma from nothing. A database that already has Atma's tables (one created
before this runner existed) must not get it again: the runner refuses until it is told, with
--baseline, that 000 is already there.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def migrations(directory: Path = MIGRATIONS) -> list[tuple[str, Path]]:
    found = []
    for p in sorted(directory.glob("*.sql")):
        m = _NAME.match(p.name)
        if not m:
            raise SystemExit(f"migration file not named NNN_name.sql: {p.name}")
        found.append((m.group(1), p))
    versions = [v for v, _ in found]
    if len(set(versions)) != len(versions):
        raise SystemExit(f"two migrations share a number: {versions}")
    return found


def _ensure_ledger(cur) -> None:
    cur.execute("create table if not exists public.schema_migrations ("
                " version text primary key, name text not null, applied_at timestamptz not null default now())")


def _applied(cur) -> set[str]:
    cur.execute("select version from public.schema_migrations")
    return {r[0] for r in cur.fetchall()}


def _has_atma_tables(cur) -> bool:
    cur.execute("select count(*) from information_schema.tables "
                "where table_schema = 'public' and table_name in ('tasks', 'tags', 'users')")
    return cur.fetchone()[0] > 0


def migrate(url: str, baseline: bool = False, status: bool = False, directory: Path = MIGRATIONS,
            out=sys.stdout) -> list[str]:
    """Apply what is pending; return the versions applied (or that would be, with status=True)."""
    todo = migrations(directory)
    con = psycopg2.connect(url, connect_timeout=8)
    try:
        with con, con.cursor() as cur:
            _ensure_ledger(cur)
            done = _applied(cur)
            if "000" not in done and _has_atma_tables(cur):
                if not baseline:
                    raise SystemExit("this database already has Atma tables but no record of 000_base.sql; "
                                     "if it is an existing Atma database, run again with --baseline")
                if not status:
                    cur.execute("insert into public.schema_migrations (version, name) values ('000', %s)",
                                ("000_base.sql (baseline: already present)",))
                    print("000 recorded as applied (baseline)", file=out)
                done.add("000")
        pending = [(v, p) for v, p in todo if v not in done]
        if status:
            for v, p in todo:
                print(f"{'applied' if v in done else 'pending'}  {p.name}", file=out)
            return [v for v, _ in pending]
        for v, p in pending:
            with con, con.cursor() as cur:
                cur.execute(p.read_text())
                cur.execute("insert into public.schema_migrations (version, name) values (%s, %s)", (v, p.name))
            print(f"applied {p.name}", file=out)
        if not pending:
            print("up to date", file=out)
        return [v for v, _ in pending]
    finally:
        con.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--database-url", default=os.environ.get("ATMA_DATABASE_URL"))
    ap.add_argument("--baseline", action="store_true", help="record 000 as applied on an existing Atma database")
    ap.add_argument("--status", action="store_true", help="list applied and pending migrations; change nothing")
    args = ap.parse_args(argv)
    if not args.database_url:
        print("no database: set ATMA_DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2
    migrate(args.database_url, baseline=args.baseline, status=args.status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
