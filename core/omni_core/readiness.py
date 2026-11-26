"""Is Omni keeping its domains alive (`readiness.domains`)? One verdict, from facts, with every reason shown.

Omni is ready only when all of these hold for the domains the registry's ``readiness`` section
names (listed under `readiness.domains`):

1. services   every service of those domains, and every core service, is running
2. jobs       no job of those domains is failed or overdue (launchd, omni run and Hermes cron alike)
3. ledger     the runs Omni fired for them in the last 24h succeeded at least ``min_success``
              of the time, and every job that should have run in that window did run through Omni
4. data       each freshness probe finds new rows inside its ``max_age``: proof the data moves,
              not just that processes exit 0

Probes are read-only: SQLite is opened with ``mode=ro`` and Postgres sessions are read-only.
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import jobstate, schedule

_AGE = re.compile(r"^(\d+)\s*([mhd])$")
_UNIT_S = {"m": 60, "h": 3600, "d": 86400}
CORE_SERVICE_DOMAIN = "omni"


class ReadinessError(ValueError):
    pass


@dataclass(frozen=True)
class Probe:
    name: str
    query: str                  # returns one value: the newest row's time as epoch seconds
    max_age_s: int
    sqlite: Optional[Path] = None
    postgres: Optional[str] = None   # env var holding the DSN


@dataclass(frozen=True)
class Spec:
    domains: tuple
    min_success: float
    probes: tuple


@dataclass
class Check:
    area: str
    name: str
    ok: bool
    detail: str


@dataclass
class Verdict:
    ready: bool
    checks: list = field(default_factory=list)

    def failures(self) -> list:
        return [c for c in self.checks if not c.ok]


def parse(raw: Optional[dict], domains: dict, base: Path) -> Optional[Spec]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ReadinessError("readiness must be a mapping")
    names = raw.get("domains")
    if not (isinstance(names, list) and names and all(n in domains for n in names)):
        raise ReadinessError("readiness.domains must list known domains")
    min_success = raw.get("min_success", 0.95)
    if not isinstance(min_success, (int, float)) or not 0 < min_success <= 1:
        raise ReadinessError("readiness.min_success must be in (0, 1]")
    probes = []
    for name, entry in (raw.get("freshness") or {}).items():
        where = f"readiness.freshness.{name}"
        if not isinstance(entry, dict) or not isinstance(entry.get("query"), str):
            raise ReadinessError(f"{where}: needs a `query`")
        if bool(entry.get("sqlite")) == bool(entry.get("postgres")):
            raise ReadinessError(f"{where}: give exactly one of `sqlite` (a path) or `postgres` (a DSN env var)")
        m = _AGE.match(str(entry.get("max_age", "")))
        if not m:
            raise ReadinessError(f"{where}: max_age like 90m, 2h or 1d")
        sqlite_path = Path(str(entry["sqlite"])).expanduser() if entry.get("sqlite") else None
        probes.append(Probe(name=name, query=entry["query"], max_age_s=int(m.group(1)) * _UNIT_S[m.group(2)],
                            sqlite=sqlite_path, postgres=entry.get("postgres")))
    return Spec(domains=tuple(names), min_success=float(min_success), probes=tuple(probes))


def probe_value(probe: Probe) -> Optional[float]:
    if probe.sqlite is not None:
        conn = sqlite3.connect(f"file:{probe.sqlite}?mode=ro", uri=True, timeout=10)
        try:
            row = conn.execute(probe.query).fetchone()
        finally:
            conn.close()
    else:
        import psycopg2
        dsn = os.environ.get(probe.postgres or "")
        if not dsn:
            raise ReadinessError(f"{probe.postgres} is not set (run under ~/bin/omni-svc)")
        conn = psycopg2.connect(dsn, connect_timeout=5,
                                options="-c default_transaction_read_only=on -c statement_timeout=15000")
        try:
            with conn.cursor() as cur:
                cur.execute(probe.query)
                row = cur.fetchone()
        finally:
            conn.close()
    value = row[0] if row else None
    return None if value is None else float(value)


def evaluate(registry, *, states: dict, services: list, runs_24h: list, now: Optional[float] = None,
             value_of: Callable[[Probe], Optional[float]] = probe_value) -> Verdict:
    """``runs_24h``: ``[(job, status, fired_by)]`` for runs started in the last 24 hours."""
    spec = registry.readiness
    if spec is None:
        return Verdict(False, [Check("config", "readiness", False, "the registry has no readiness section")])
    now = time.time() if now is None else now
    domains = set(spec.domains)
    checks = []

    for svc in services:
        if svc.domain in domains or svc.domain == CORE_SERVICE_DOMAIN:
            port = "" if svc.port is None else f"; port {svc.port} {'open' if svc.port_open else 'closed'}"
            checks.append(Check("services", svc.name, svc.ok, f"{svc.state}{port}"))

    jobs = [j for j in registry.jobs.values() if j.domain in domains and (j.enabled or j.hermes_cron)]
    for job in jobs:
        st = states[job.name]
        checks.append(Check("jobs", job.name, st.status not in ("failed", "overdue"),
                            f"{st.status}: {st.detail}"))

    fired = [r for r in runs_24h if r[2] == "omni" and registry.jobs.get(r[0]) is not None
             and registry.jobs[r[0]].domain in domains and r[1] not in ("running", "refused")]
    ok = sum(1 for r in fired if r[1] == "ok")
    rate = ok / len(fired) if fired else 0.0
    checks.append(Check("ledger", "success rate", bool(fired) and rate >= spec.min_success,
                        f"{ok} of {len(fired)} runs ok in 24h ({rate:.0%}; needs {spec.min_success:.0%})"))
    ran = {r[0] for r in runs_24h if r[2] == "omni"}
    for job in jobs:
        if job.launchd and job.schedule and schedule.interval_s(job.schedule) <= 86400:
            checks.append(Check("ledger", f"{job.name} ran", job.name in ran,
                                "ran through omni in the last 24h" if job.name in ran
                                else "no run through omni in the last 24h"))

    for probe in spec.probes:
        try:
            newest = value_of(probe)
        except Exception as exc:          # a probe that cannot run is a failed check, not a crash
            checks.append(Check("data", probe.name, False, f"probe failed: {str(exc).splitlines()[0][:160]}"))
            continue
        if newest is None:
            checks.append(Check("data", probe.name, False, "no rows"))
            continue
        age = now - newest
        checks.append(Check("data", probe.name, age <= probe.max_age_s,
                            f"newest {jobstate.ago(age)} old (limit {jobstate.ago(probe.max_age_s)})"))
    return Verdict(all(c.ok for c in checks), checks)


def render(verdict: Verdict) -> list:
    """Every failing check, the data and success-rate checks always, the rest as counts."""
    lines = [f"Omni is {'READY' if verdict.ready else 'NOT READY'} to run its domains"]
    for area in ("config", "services", "jobs", "ledger", "data"):
        group = [c for c in verdict.checks if c.area == area]
        if not group:
            continue
        lines.append(f"  {area}: {sum(c.ok for c in group)} of {len(group)} ok")
        for c in group:
            if not c.ok or area == "data" or c.name == "success rate":
                lines.append(f"    {'ok  ' if c.ok else 'FAIL'} {c.name:<36} {c.detail}")
    return lines
