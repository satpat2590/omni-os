"""Hermes cron as a harness Omni watches: its jobs' state, and its runs copied into the ledger.

Hermes keeps the personality jobs (agents with a persona): their skills, memory
and delivery live there. Omni does not fire them. It reads, never writes, two things per profile:

    <profile>/cron/jobs.json   each job's schedule, last status, last error, next run
    <profile>/state.db         one session per agent run, with tokens and cost

``sync`` copies finished cron sessions into ``core.runs`` (``fired_by = 'hermes-cron'``, keyed by
the session id so a re-import adds nothing), which puts Hermes spend in the same ledger, budget
view and readiness check as everything else. A session is matched to its job by its title, which
Hermes sets to ``<job name> · <time>``.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

HERMES_HOME = Path.home() / ".hermes"
LOOKBACK_S = 3 * 86400          # every sync re-reads this window; the unique key drops repeats
LATE_GRACE_S = 1800             # a job is overdue this long after the run Hermes said was next
FIRED_BY = "hermes-cron"


def profile_dir(profile: str, home: Path = HERMES_HOME) -> Path:
    return home if profile == "default" else home / "profiles" / profile


def read_jobs(profile: str, home: Path = HERMES_HOME) -> dict:
    """``{job id: job dict}`` from the profile's jobs.json; empty when it cannot be read."""
    try:
        raw = json.loads((profile_dir(profile, home) / "cron" / "jobs.json").read_text())
    except (OSError, ValueError):
        return {}
    jobs = raw if isinstance(raw, list) else raw.get("jobs", [])
    return {j["id"]: j for j in jobs if isinstance(j, dict) and "id" in j}


def _epoch(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


@dataclass
class CronFacts:
    found: bool
    enabled: bool = False
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    failure_streak: int = 0
    schedule: str = ""


def facts(profile: str, job_id: str, home: Path = HERMES_HOME) -> CronFacts:
    job = read_jobs(profile, home).get(job_id)
    if job is None:
        return CronFacts(found=False)
    return CronFacts(found=True, enabled=bool(job.get("enabled")) and not job.get("paused_at"),
                     last_status=job.get("last_status"), last_error=job.get("last_error"),
                     last_run=_epoch(job.get("last_run_at")), next_run=_epoch(job.get("next_run_at")),
                     failure_streak=int(job.get("failure_streak") or 0),
                     schedule=str(job.get("schedule_display") or ""))


def judge(facts_: CronFacts, now: float):
    """``(status, detail)`` in the vocabulary of jobstate."""
    from .jobstate import ago
    if not facts_.found:
        return "failed", "not found in Hermes cron (removed or renamed?)"
    if not facts_.enabled:
        return "unknown", "paused in Hermes"
    seen = "never ran" if facts_.last_run is None else f"last run {ago(now - facts_.last_run)} ago"
    if facts_.last_status not in (None, "ok"):
        error = (facts_.last_error or "").strip().splitlines()
        return "failed", f"{seen}: {facts_.last_status}" + (f" ({error[0][:120]})" if error else "")
    if facts_.next_run is not None and now > facts_.next_run + LATE_GRACE_S:
        return "overdue", f"{seen}; was due {ago(now - facts_.next_run)} ago"
    if facts_.last_run is None:
        return "waiting", "has not run yet"
    return "ok", seen


def _sessions(profile: str, since: float, home: Path = HERMES_HOME) -> list:
    db = profile_dir(profile, home) / "state.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        return conn.execute(
            "select id, title, model, started_at, ended_at, end_reason, input_tokens, output_tokens, "
            "actual_cost_usd, estimated_cost_usd from sessions "
            "where source = 'cron' and started_at >= ? and ended_at is not null", (since,)).fetchall()
    finally:
        conn.close()


def sync(registry, ledger, *, home: Path = HERMES_HOME, now: Optional[float] = None) -> dict:
    """Copy finished Hermes cron sessions into the ledger. Returns counts per outcome."""
    now = time.time() if now is None else now
    by_title = {}            # (profile, Hermes job name) -> registry job
    for job in registry.jobs.values():
        if job.hermes_cron:
            hermes_job = read_jobs(job.profile or "default", home).get(job.hermes_cron)
            if hermes_job:
                by_title[(job.profile or "default", hermes_job.get("name", ""))] = job
    profiles = {"default"} | {j.profile for j in registry.jobs.values() if j.hermes_cron and j.profile}
    counts = {"recorded": 0, "already": 0, "unmatched": 0}
    for profile in sorted(profiles):
        for (sid, title, model, started, ended, end_reason, tin, tout, actual, estimated) in \
                _sessions(profile, now - LOOKBACK_S, home):
            name = (title or "").split(" · ")[0]
            job = by_title.get((profile, name))
            if job is None:
                if not (actual or estimated):
                    continue        # an untitled wake-up that cost nothing: nothing to record
                counts["unmatched"] += 1
                job_name, domain = f"hermes:{profile}", "omni"
            else:
                job_name, domain = job.name, job.domain
            cost = actual if actual is not None else estimated
            status = "ok" if end_reason in (None, "cron_complete") else "failed"
            new = ledger.record_external(
                external_id=f"hermes:{profile}:{sid}", fired_by=FIRED_BY, job=job_name, domain=domain,
                harness="hermes", model=model, status=status,
                reason=None if status == "ok" else end_reason, started_epoch=started,
                ended_epoch=ended, cost_usd=cost,
                cost_source="hermes_session" if cost is not None else "unknown",
                tokens_in=tin, tokens_out=tout, registry_sha=registry.sha)
            counts["recorded" if new else "already"] += 1
    return counts
