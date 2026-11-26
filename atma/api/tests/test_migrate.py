"""scripts/migrate.py: Atma from nothing, idempotent re-runs, and adopting an existing database."""
import io

import psycopg2
import pytest

from migrate import migrate, migrations


def _one(url, q):
    con = psycopg2.connect(url)
    try:
        with con.cursor() as cur:
            cur.execute(q)
            rows = cur.fetchall() if cur.description else []
        con.commit()
        return rows
    finally:
        con.close()


def test_migrations_are_numbered_and_start_with_the_base():
    found = migrations()
    assert found and found[0][0] == "000" and found[0][1].name == "000_base.sql"


def test_a_fresh_database_gets_all_of_atma_and_a_second_run_changes_nothing(make_database):
    url = make_database()
    assert migrate(url, out=io.StringIO()) == ["000"] + [v for v, _ in migrations()][1:]
    kinds = dict(_one(url, "select relkind, count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                           "where nspname = 'public' and relkind in ('r', 'v') group by relkind"))
    assert kinds == {"r": 14, "v": 3}          # 13 Atma tables + schema_migrations; 3 views
    assert _one(url, "select version from schema_migrations order by version")[0] == ("000",)
    out = io.StringIO()
    assert migrate(url, out=out) == [] and "up to date" in out.getvalue()


def test_the_base_schema_carries_no_domain_or_supabase_leftovers(make_database):
    url = make_database()
    migrate(url, out=io.StringIO())
    tables = {t for (t,) in _one(url, "select table_name from information_schema.tables where table_schema='public'")}
    assert "candidate_gates" not in tables
    assert _one(url, "select count(*) from pg_policies")[0][0] == 0
    with pytest.raises(psycopg2.errors.CheckViolation):
        _one(url, "insert into tasks (title, category) values ('x', 'edoras')")


def test_an_existing_atma_database_needs_baseline_and_is_not_rebuilt(make_database):
    url = make_database()
    # an Atma database from before Omni OS: the owner's tasks carried a person's name as owner_type
    _one(url, "create table users (id serial primary key, name text not null); "
              "create table tasks (id serial primary key, title text, "
              "owner_type character varying default 'someone'); "
              "insert into tasks (title) values ('old'); insert into tasks (title, owner_type) values ('a', 'agent'); "
              "select 1")
    with pytest.raises(SystemExit, match="--baseline"):
        migrate(url, out=io.StringIO())
    migrate(url, baseline=True, out=io.StringIO())
    assert ("000",) in _one(url, "select version from schema_migrations")
    assert [c for (c,) in _one(url, "select column_name from information_schema.columns where table_name='users'")] \
        == ["id", "name"]                       # 000 recorded, not run over the existing table
    assert _one(url, "select title, owner_type from tasks order by id") == [("old", "owner"), ("a", "agent")]
    assert _one(url, "select column_default from information_schema.columns "
                     "where table_name='tasks' and column_name='owner_type'")[0][0].startswith("'owner'")
