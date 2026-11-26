"""The run ledger: one Postgres row per run, in Omni's own database.

It lives in its own ``omni`` database, so the core never shares a schema with a domain. The DSN is
``OMNI_DATABASE_URL``, which ``core/bin/omni-svc`` loads from ``~/.config/omni/*.env``.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Optional

CORE_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = CORE_DIR / "migrations"
DATABASE = "omni"
CONNECT_TIMEOUT_S = 5


class LedgerError(RuntimeError):
    """The ledger cannot be reached or written."""


def dsn(env: Optional[dict] = None) -> str:
    env = os.environ if env is None else env
    if env.get("OMNI_DATABASE_URL"):
        return env["OMNI_DATABASE_URL"]
    raise LedgerError("no ledger DSN: set OMNI_DATABASE_URL (core/bin/omni-svc loads it from ~/.config/omni)")


class Ledger:
    def __init__(self, dsn_url: Optional[str] = None):
        self._dsn = dsn_url

    def _connect(self):
        import psycopg2

        try:
            conn = psycopg2.connect(self._dsn or dsn(), connect_timeout=CONNECT_TIMEOUT_S)
        except psycopg2.Error as exc:
            # str(exc) can echo the DSN's host and user but not the password; keep it to one line.
            raise LedgerError(f"cannot connect to the ledger: {str(exc).strip().splitlines()[0]}") from exc
        conn.autocommit = True
        return conn

    def _execute(self, sql: str, args=None, fetch: bool = False):
        import psycopg2

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                return cur.fetchall() if fetch else None
        except psycopg2.Error as exc:
            raise LedgerError(f"ledger query failed: {str(exc).strip().splitlines()[0]}") from exc
        finally:
            conn.close()

    def ping(self) -> None:
        self._execute("select 1 from core.runs limit 1")

    def migrate(self) -> list:
        """Apply every ``migrations/*.sql`` in name order. Each file is idempotent."""
        applied = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            self._execute(path.read_text())
            applied.append(path.name)
        return applied

    def start(self, *, job: str, domain: str, harness: str, model: Optional[str],
              registry_sha: str, log_path: Optional[str]) -> int:
        rows = self._execute(
            "insert into core.runs (job, domain, harness, model, status, registry_sha, host, log_path) "
            "values (%s, %s, %s, %s, 'running', %s, %s, %s) returning id",
            (job, domain, harness, model, registry_sha, socket.gethostname(), log_path), fetch=True)
        return rows[0][0]

    def record_external(self, *, external_id: str, fired_by: str, job: str, domain: str,
                        harness: str, model: Optional[str], status: str, reason: Optional[str],
                        started_epoch: float, ended_epoch: Optional[float], cost_usd: Optional[float],
                        cost_source: str, tokens_in: Optional[int], tokens_out: Optional[int],
                        registry_sha: str) -> bool:
        """Record a run something else started. Returns False when it was already recorded."""
        rows = self._execute(
            "insert into core.runs (external_id, fired_by, job, domain, harness, model, status, reason, "
            "started_at, ended_at, cost_usd, cost_source, tokens_in, tokens_out, registry_sha, host) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s), %s, %s, %s, %s, %s, %s) "
            "on conflict (external_id) where external_id is not null do nothing returning id",
            (external_id, fired_by, job, domain, harness, model, status, reason, started_epoch,
             ended_epoch, cost_usd, cost_source, tokens_in, tokens_out, registry_sha,
             socket.gethostname()), fetch=True)
        return bool(rows)

    def finish(self, run_id: int, *, status: str, exit_code: Optional[int], reason: Optional[str],
               cost_usd: Optional[float], cost_source: str, tokens_in: Optional[int],
               tokens_out: Optional[int], model: Optional[str]) -> None:
        self._execute(
            "update core.runs set status=%s, exit_code=%s, reason=%s, cost_usd=%s, cost_source=%s, "
            "tokens_in=%s, tokens_out=%s, model=coalesce(%s, model), ended_at=now() where id=%s",
            (status, exit_code, reason, cost_usd, cost_source, tokens_in, tokens_out, model, run_id))

    def refuse(self, *, job: str, domain: str, harness: str, model: Optional[str],
               registry_sha: str, reason: str) -> int:
        rows = self._execute(
            "insert into core.runs (job, domain, harness, model, status, reason, registry_sha, host, "
            "ended_at) values (%s, %s, %s, %s, 'refused', %s, %s, %s, now()) returning id",
            (job, domain, harness, model, reason, registry_sha, socket.gethostname()), fetch=True)
        return rows[0][0]

    def month_spend(self, job: str) -> float:
        """Known spend for ``job`` in the current calendar month."""
        rows = self._execute(
            "select coalesce(sum(cost_usd), 0) from core.runs "
            "where job=%s and started_at >= date_trunc('month', now())", (job,), fetch=True)
        return float(rows[0][0])

    def month_unknown(self, job: str) -> int:
        """Finished runs of ``job`` this month whose cost is unknown: a cap cannot count them."""
        rows = self._execute(
            "select count(*) from core.runs where job=%s and cost_usd is null "
            "and status in ('ok', 'failed', 'timeout') "
            "and started_at >= date_trunc('month', now())", (job,), fetch=True)
        return int(rows[0][0])

    def last_runs(self) -> dict:
        """``{job: (status, reason, ended_epoch)}`` for each job's newest ledger row."""
        rows = self._execute(
            "select distinct on (job) job, status, reason, "
            "extract(epoch from coalesce(ended_at, started_at))::float8 "
            "from core.runs order by job, started_at desc", fetch=True)
        return {job: (status, reason, ended) for job, status, reason, ended in rows}

    def runs_since(self, hours: int) -> list:
        """``[(job, status, fired_by)]`` for runs started in the last ``hours``."""
        return self._execute(
            "select job, status, fired_by from core.runs "
            "where started_at >= now() - make_interval(hours => %s)", (hours,), fetch=True)

    def spend(self, days: int) -> list:
        """Per job and harness over the last ``days``: runs, failures, runs of unknown cost, spend."""
        return self._execute(
            "select job, harness, count(*) filter (where status <> 'refused'), "
            "count(*) filter (where status in ('failed', 'timeout')), "
            "count(*) filter (where status <> 'refused' and cost_usd is null), "
            "coalesce(sum(cost_usd), 0)::float8 "
            "from core.runs where started_at >= now() - make_interval(days => %s) "
            "group by 1, 2 order by 6 desc, 1", (days,), fetch=True)
