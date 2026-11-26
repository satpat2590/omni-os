"""Atma's database: plain Postgres through psycopg2, behind a small query builder.

Atma's API was written against Supabase's PostgREST client. This module keeps that call shape,

    db.table("tasks").select("*").eq("is_active", True).order("id").execute().data

so moving to plain Postgres changed the transport and not the API's logic. Results look like
PostgREST's: a list of dicts with JSON-friendly values (timestamps and dates as ISO strings,
numerics as numbers), and insert/update/delete return the rows they wrote.

Only identifiers that look like plain column/table names are accepted, and every value is a bound
parameter. Raw SQL goes through `db.query(sql, params)`.

The connection comes from ATMA_DATABASE_URL (omni-svc loads it from ~/.config). Nothing connects
until the first query, so importing Atma never needs a database.
"""
from __future__ import annotations

import datetime as _dt
import decimal
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool
from psycopg2 import sql

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ident(name: str) -> sql.Identifier:
    if not isinstance(name, str) or not _IDENT.match(name):
        raise ValueError(f"not a plain identifier: {name!r}")
    return sql.Identifier(name)


def _jsonable(value: Any) -> Any:
    """A psycopg2 value as PostgREST would have returned it."""
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _rows(cur) -> list[dict]:
    if cur.description is None:
        return []
    return [{k: _jsonable(v) for k, v in row.items()} for row in cur.fetchall()]


@dataclass
class Result:
    data: list = field(default_factory=list)


class Database:
    """A lazily connected pool of psycopg2 connections to one Atma database."""

    def __init__(self, url: Optional[str] = None, maxconn: int = 8):
        self._url = url
        self._maxconn = maxconn
        self._pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
        self._pool_url: Optional[str] = None
        self._lock = threading.Lock()
        self._json_columns: dict[str, set[str]] = {}

    def url(self) -> str:
        url = self._url or os.environ.get("ATMA_DATABASE_URL")
        if not url:
            raise RuntimeError("ATMA_DATABASE_URL is not set (run Atma through omni-svc)")
        return url

    def _get_pool(self) -> psycopg2.pool.ThreadedConnectionPool:
        url = self.url()
        with self._lock:
            if self._pool is None or self._pool_url != url:   # a test may point ATMA_DATABASE_URL elsewhere
                if self._pool is not None:
                    self._pool.closeall()
                self._pool = psycopg2.pool.ThreadedConnectionPool(1, self._maxconn, dsn=url, connect_timeout=8)
                self._pool_url = url
                self._json_columns.clear()
            return self._pool

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.closeall()
                self._pool = None

    @contextmanager
    def cursor(self):
        """One transaction: commit on success, roll back on any exception."""
        pool = self._get_pool()
        con = pool.getconn()
        try:
            with con.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                yield cur
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            pool.putconn(con)

    def query(self, statement, params: Iterable = ()) -> list[dict]:
        with self.cursor() as cur:
            cur.execute(statement, tuple(params))
            return _rows(cur)

    def table(self, name: str) -> "Query":
        return Query(self, name)

    def json_columns(self, table: str) -> set[str]:
        """The table's json/jsonb columns, so dict and list values are written as JSON."""
        if table not in self._json_columns:
            rows = self.query(
                "select column_name from information_schema.columns "
                "where table_schema = 'public' and table_name = %s and data_type in ('json', 'jsonb')",
                (table,))
            self._json_columns[table] = {r["column_name"] for r in rows}
        return self._json_columns[table]


class Query:
    """One statement against one table, built up PostgREST-style and run by execute()."""

    def __init__(self, db: Database, table: str):
        _ident(table)
        self._db = db
        self._table = table
        self._action = "select"
        self._columns: list[str] | None = None        # None = *
        self._values: list[dict] | dict | None = None
        self._where: list[tuple[sql.Composable, list]] = []
        self._order: list[tuple[str, bool]] = []
        self._limit: Optional[int] = None
        self._offset: Optional[int] = None

    # ---- what to do
    def select(self, columns: str = "*") -> "Query":
        self._action = "select"
        cols = [c.strip() for c in columns.split(",") if c.strip()]
        if cols == ["*"]:
            self._columns = None
        else:
            if any("(" in c or ":" in c for c in cols):
                raise ValueError(f"embedded resources and aliases are not supported: {columns!r} (write a join with db.query)")
            for c in cols:
                _ident(c)
            self._columns = cols
        return self

    def insert(self, values) -> "Query":
        self._action, self._values = "insert", values
        return self

    def update(self, values: dict) -> "Query":
        self._action, self._values = "update", values
        return self

    def delete(self) -> "Query":
        self._action = "delete"
        return self

    # ---- filters
    def _cmp(self, column: str, op: str, value) -> "Query":
        self._where.append((sql.SQL("{} " + op + " %s").format(_ident(column)), [value]))
        return self

    def eq(self, column, value):  return self._cmp(column, "=", value)
    def neq(self, column, value): return self._cmp(column, "<>", value)
    def gt(self, column, value):  return self._cmp(column, ">", value)
    def gte(self, column, value): return self._cmp(column, ">=", value)
    def lt(self, column, value):  return self._cmp(column, "<", value)
    def lte(self, column, value): return self._cmp(column, "<=", value)

    def in_(self, column: str, values) -> "Query":
        self._where.append((sql.SQL("{} = any(%s)").format(_ident(column)), [list(values)]))
        return self

    def is_(self, column: str, value) -> "Query":
        if value in (None, "null"):
            self._where.append((sql.SQL("{} is null").format(_ident(column)), []))
        elif value in (True, "true"):
            self._where.append((sql.SQL("{} is true").format(_ident(column)), []))
        elif value in (False, "false"):
            self._where.append((sql.SQL("{} is false").format(_ident(column)), []))
        else:
            raise ValueError(f"is_ takes null, true or false, not {value!r}")
        return self

    def match(self, conditions: dict) -> "Query":
        for column, value in conditions.items():
            self.eq(column, value)
        return self

    # ---- shape
    def order(self, column: str, desc: bool = False) -> "Query":
        _ident(column)
        self._order.append((column, desc))
        return self

    def limit(self, n: int) -> "Query":
        self._limit = int(n)
        return self

    def range(self, start: int, end: int) -> "Query":
        """Rows start..end inclusive, as in PostgREST."""
        self._offset, self._limit = int(start), int(end) - int(start) + 1
        return self

    # ---- run
    def _adapt(self, row: dict) -> dict:
        jsoncols = self._db.json_columns(self._table)
        out = {}
        for k, v in row.items():
            _ident(k)
            if isinstance(v, dict) or (k in jsoncols and isinstance(v, list)):
                v = psycopg2.extras.Json(v)
            out[k] = v
        return out

    def _where_sql(self):
        if not self._where:
            return sql.SQL(""), []
        parts, params = [], []
        for clause, p in self._where:
            parts.append(clause)
            params.extend(p)
        return sql.SQL(" where ") + sql.SQL(" and ").join(parts), params

    def build(self):
        """(statement, params): exposed so tests can see exactly what runs."""
        t = _ident(self._table)
        where, params = self._where_sql()
        if self._action == "select":
            cols = sql.SQL("*") if self._columns is None else sql.SQL(", ").join(map(_ident, self._columns))
            stmt = sql.SQL("select {} from {}").format(cols, t) + where
            if self._order:
                stmt += sql.SQL(" order by ") + sql.SQL(", ").join(
                    sql.SQL("{} {}").format(_ident(c), sql.SQL("desc" if d else "asc")) for c, d in self._order)
            if self._limit is not None:
                stmt += sql.SQL(" limit %s")
                params.append(self._limit)
            if self._offset is not None:
                stmt += sql.SQL(" offset %s")
                params.append(self._offset)
            return stmt, params
        if self._action == "insert":
            rows = self._values if isinstance(self._values, list) else [self._values]
            if not rows:
                raise ValueError("insert needs at least one row")
            rows = [self._adapt(r) for r in rows]
            cols = list(rows[0])
            if any(list(r) != cols for r in rows):
                raise ValueError("every inserted row must have the same columns")
            values = sql.SQL(", ").join(
                sql.SQL("({})").format(sql.SQL(", ").join(sql.Placeholder() * len(cols))) for _ in rows)
            stmt = sql.SQL("insert into {} ({}) values {} returning *").format(
                t, sql.SQL(", ").join(map(_ident, cols)), values)
            return stmt, [r[c] for r in rows for c in cols]
        if self._action == "update":
            if not self._where:
                raise ValueError("update without a filter would change every row")
            row = self._adapt(self._values)
            sets = sql.SQL(", ").join(sql.SQL("{} = %s").format(_ident(c)) for c in row)
            stmt = sql.SQL("update {} set {}").format(t, sets) + where + sql.SQL(" returning *")
            return stmt, list(row.values()) + params
        if self._action == "delete":
            if not self._where:
                raise ValueError("delete without a filter would remove every row")
            return sql.SQL("delete from {}").format(t) + where + sql.SQL(" returning *"), params
        raise ValueError(f"unknown action {self._action}")

    def execute(self) -> Result:
        stmt, params = self.build()
        with self._db.cursor() as cur:
            cur.execute(stmt, params)
            return Result(_rows(cur))


db = Database()
