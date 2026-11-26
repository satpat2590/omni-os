"""What each registered job last did, from facts the platform already keeps.

A job fired by launchd directly is judged from three things: launchd's last exit code for it, the
modification time of its log file (the plist's ``StandardOutPath``), and its interval from the
same plist. A job run through ``omni run`` is judged from its newest ledger row. No domain's own
monitoring is consulted, so this view keeps working when a domain's heartbeat recorder does not.

Statuses: ``ok``, ``failed`` (last exit code was not 0), ``overdue`` (no log activity for more
than twice its interval), ``waiting`` (has not run since boot and is not overdue yet), ``unknown``.
"""
from __future__ import annotations

import plistlib
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import hermes_cron, schedule
from .registry import Job, Registry

PLIST_DIR = Path("/Library/LaunchDaemons")
DAY_S = 86400


@dataclass
class LaunchdFacts:
    loaded: bool
    last_exit: Optional[int]       # None = has not exited since boot
    runs: Optional[int]
    running: bool = False


@dataclass
class JobState:
    name: str
    status: str
    detail: str
    last_activity: Optional[float] = None   # epoch seconds
    interval_s: Optional[int] = None
    fired_by: str = "launchd"                # launchd | omni | hermes | nobody


def launchd_facts(label: str) -> LaunchdFacts:
    try:
        proc = subprocess.run(["launchctl", "print", f"system/{label}"], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return LaunchdFacts(loaded=False, last_exit=None, runs=None)
    if proc.returncode != 0:
        return LaunchdFacts(loaded=False, last_exit=None, runs=None)
    last_exit, runs, running = None, None, False
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if raw.startswith("\tstate = "):          # the job's own state, not a nested endpoint's
            running = line.split("= ", 1)[1] == "running"
        elif line.startswith("last exit code = "):
            value = line.split("= ", 1)[1]
            last_exit = int(value) if value.lstrip("-").isdigit() else None
        elif line.startswith("runs = "):
            value = line.split("= ", 1)[1]
            runs = int(value) if value.isdigit() else None
    return LaunchdFacts(loaded=True, last_exit=last_exit, runs=runs, running=running)


def plist_facts(label: str, plist_dir: Path = PLIST_DIR) -> tuple:
    """``(interval_s, log_path)`` from the job's plist; either may be None."""
    try:
        with open(plist_dir / f"{label}.plist", "rb") as f:
            plist = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None, None
    interval = plist.get("StartInterval")
    if not isinstance(interval, int):
        calendar = plist.get("StartCalendarInterval")
        slots = calendar if isinstance(calendar, list) else [calendar] if calendar else []
        if not slots:
            interval = None
        elif any("Weekday" in slot for slot in slots):
            interval = 4 * DAY_S       # weekday-only slots: quiet over a long weekend is normal
        elif any("Hour" in slot for slot in slots):
            interval = DAY_S
        else:
            interval = 3600            # minute-only slots fire hourly
    log = plist.get("StandardOutPath")
    return interval, Path(log) if isinstance(log, str) else None


def _mtime(path: Optional[Path]) -> Optional[float]:
    """Newest modification time of ``path``; a ``*`` in its name matches dated log files."""
    if path is None:
        return None
    path = Path(path).expanduser()
    candidates = list(path.parent.glob(path.name)) if "*" in path.name else [path]
    times = []
    for candidate in candidates:
        try:
            times.append(candidate.stat().st_mtime)
        except OSError:
            continue
    return max(times) if times else None


def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 2 * DAY_S:
        return f"{seconds // 3600}h"
    return f"{seconds // DAY_S}d"


def judge_launchd(job: Job, facts: LaunchdFacts, interval_s: Optional[int],
                  last_activity: Optional[float], now: float) -> JobState:
    base = dict(name=job.name, last_activity=last_activity, interval_s=interval_s, fired_by="launchd")
    if not facts.loaded:
        return JobState(status="failed", detail=f"{job.launchd} is not loaded in launchd", **base)
    seen = "no log activity" if last_activity is None else f"last activity {ago(now - last_activity)} ago"
    if facts.running:
        return JobState(status="ok", detail=f"running now; {seen}", **base)
    if facts.last_exit not in (None, 0):
        return JobState(status="failed", detail=f"last exit code {facts.last_exit}; {seen}", **base)
    if interval_s and last_activity is not None and now - last_activity > 2 * interval_s:
        return JobState(status="overdue", detail=f"{seen}, more than twice its interval", **base)
    if facts.last_exit is None and not facts.runs:
        if last_activity is None:
            return JobState(status="unknown", detail="has not run since boot; no log found", **base)
        return JobState(status="waiting", detail=f"has not run since boot; {seen}", **base)
    if last_activity is None:
        return JobState(status="unknown", detail="exited 0 but no log found", **base)
    return JobState(status="ok", detail=seen, **base)


def judge_ledger(job: Job, row: Optional[tuple], now: float) -> JobState:
    """``row`` is the newest ledger run: ``(status, reason, ended_epoch)`` or None."""
    base = dict(name=job.name, fired_by="omni")
    if row is None:
        return JobState(status="unknown", detail="no run in the ledger yet", **base)
    status, reason, ended = row
    seen = "" if ended is None else f"; ended {ago(now - ended)} ago"
    if status == "ok":
        return JobState(status="ok", detail=f"last run ok{seen}", last_activity=ended, **base)
    if status == "running":
        return JobState(status="ok", detail="running now", last_activity=ended, **base)
    return JobState(status="failed", detail=f"last run {status}: {reason or 'no reason recorded'}{seen}",
                    last_activity=ended, **base)


def judge_omni_timer(job: Job, facts: LaunchdFacts, interval_s: Optional[int],
                     row: Optional[tuple], now: float) -> JobState:
    """A job launchd fires on a timer through ``omni run``: the ledger says how its runs went,
    launchd says whether the timer is loaded, and the interval says whether it is overdue."""
    base = dict(name=job.name, interval_s=interval_s, fired_by="omni")
    if not facts.loaded:
        return JobState(status="failed", detail=f"{job.launchd} is not loaded in launchd", **base)
    if row is None:
        return JobState(status="ok" if facts.running else "waiting",
                        detail="running now; no finished run in the ledger yet" if facts.running
                        else "no run in the ledger yet", **base)
    status, reason, ended = row
    base["last_activity"] = ended
    seen = "" if ended is None else f"ended {ago(now - ended)} ago"
    if status == "running" or facts.running:
        if status == "running" and ended is not None and now - ended > job.timeout_s + 2 * 3600:
            return JobState(status="failed", detail=f"ledger row still says running, started "
                            f"{ago(now - ended)} ago, well past its {job.timeout_s}s timeout", **base)
        return JobState(status="ok", detail="running now", **base)
    if status != "ok":
        return JobState(status="failed", detail=f"last run {status}: {reason or 'no reason recorded'}; {seen}",
                        **base)
    if interval_s and ended is not None and now - ended > 2 * interval_s:
        return JobState(status="overdue", detail=f"last run ok but {seen}, more than twice its interval",
                        **base)
    return JobState(status="ok", detail=f"last run ok; {seen}", **base)


def job_states(registry: Registry, *, last_runs: Optional[dict] = None,
               facts_of: Callable[[str], LaunchdFacts] = launchd_facts,
               plist_of: Callable[[str], tuple] = plist_facts,
               mtime_of: Callable[[Optional[Path]], Optional[float]] = _mtime,
               hermes_of: Optional[Callable] = None,
               now: Optional[float] = None) -> dict:
    """``{job name: JobState}``. ``last_runs`` maps job name to its newest ledger row, if any."""
    now = time.time() if now is None else now
    last_runs = last_runs or {}
    if hermes_of is None:
        hermes_of = lambda job: hermes_cron.facts(job.profile or "default", job.hermes_cron)
    out = {}
    for job in registry.jobs.values():
        if job.hermes_cron:
            status, detail = hermes_cron.judge(hermes_of(job), now)
            out[job.name] = JobState(name=job.name, status=status, detail=detail, fired_by="hermes")
        elif job.enabled and job.launchd:
            interval_s, _ = plist_of(job.launchd)
            if job.schedule:
                interval_s = schedule.interval_s(job.schedule)
            out[job.name] = judge_omni_timer(job, facts_of(job.launchd), interval_s,
                                             last_runs.get(job.name), now)
        elif job.enabled:
            out[job.name] = judge_ledger(job, last_runs.get(job.name), now)
        elif job.launchd:
            interval_s, log = plist_of(job.launchd)
            if job.log:      # the wrapper script redirects its output away from the plist's path
                log = Path(job.log)
            out[job.name] = judge_launchd(job, facts_of(job.launchd), interval_s, mtime_of(log), now)
        else:
            out[job.name] = JobState(name=job.name, status="unknown", fired_by="nobody",
                                     detail="disabled and not fired by launchd")
    return out


SEVERITY = ("failed", "overdue", "unknown", "waiting", "ok")


def worst(statuses) -> str:
    """The status a group shows: its worst member's."""
    statuses = list(statuses)
    for status in SEVERITY:
        if status in statuses:
            return status
    return "unknown"
