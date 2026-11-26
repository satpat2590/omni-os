"""Run one registered job: check it may run, dispatch it to its harness, record what happened.

Order of checks, each of which refuses the run and leaves a ledger row saying why:
job disabled -> harness not installed -> workdir missing -> monthly budget.

Ledger outages. An agent job is refused when the ledger is unreachable: its spend could not be
recorded or capped. A script job costs nothing and may be a data collector, so it runs anyway and
its record goes to ``state/ledger_fallback.jsonl``; the ledger must never be what stops a feed.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import adapters
from .ledger import LedgerError
from .registry import CORE_DIR, Job, Registry

STATE_DIR = CORE_DIR / "state"
# This machine's rules (instance branch) when present, else the base Omni OS rules.
RULES_PATH = (CORE_DIR / "rules" / "GLOBAL.md") if (CORE_DIR / "rules" / "GLOBAL.md").exists() \
    else (CORE_DIR / "rules" / "GLOBAL.example.md")

EXIT_REFUSED = 64      # the run was not allowed to start
EXIT_TIMEOUT = 124
EXIT_NO_LEDGER = 75    # EX_TEMPFAIL: agent job refused because the ledger is down
TERM_GRACE_S = 30      # SIGTERM first; SIGKILL only if the job is still alive this long after
RUN_LOG_DAYS = 14
LAUNCHD_STOP_GRACE_S = 15  # launchd's default ExitTimeOut is 20s


@dataclass
class Result:
    status: str                 # ok | failed | timeout | refused
    exit_code: int
    run_id: Optional[int] = None
    reason: Optional[str] = None
    cost_usd: Optional[float] = None
    log_path: Optional[Path] = None


def compose_prompt(job: Job, rules_path: Path = RULES_PATH) -> Optional[str]:
    """The job's prompt, with the global rules in front unless the job opts out."""
    if job.prompt is None:
        return None
    if not job.rules:
        return job.prompt
    try:
        rules = rules_path.read_text().strip()
    except OSError as exc:
        raise RuntimeError(f"global rules missing at {rules_path}: {exc}") from exc
    return f"{rules}\n\n---\n\n{job.prompt}"


@dataclass
class Execution:
    status: str          # ok | failed | timeout
    exit_code: int
    reason: Optional[str]
    stdout: str          # captured only when asked for (agent jobs: cost is parsed from it)


def job_workdir(registry: Registry, job: Job) -> Path:
    return job.workdir or registry.domains[job.domain].workdir


def execute(argv, *, cwd: Path, timeout_s: int, log, out=sys.stdout, err=sys.stderr,
            keep_stdout: bool = False, grace_s: float = TERM_GRACE_S, env: Optional[dict] = None) -> Execution:
    """Run ``argv`` in its own process group, streaming its output as it comes.

    Each line goes to ``out``/``err`` at once (under launchd that is the job's log file, so a
    long job is visible while it runs) and to ``log``, the binary run log. On timeout, or when this
    process is sent SIGTERM/SIGINT (launchd stopping the job), the whole group gets SIGTERM, then
    SIGKILL after ``grace_s``: a job is never cut off mid-write without a chance to finish.
    """
    lock = threading.Lock()
    kept: list = []

    try:
        # stdin is closed: `opencode run` blocks forever on an open, silent stdin.
        proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True,
                                env={**os.environ, **env} if env else None)
    except OSError as exc:
        log.write(f"could not start: {exc}\n".encode())
        return Execution("failed", 127, f"could not start: {exc}", "")

    def pump(pipe, stream, tag: bytes, keep: bool):
        for line in iter(pipe.readline, b""):
            text = line.decode(errors="replace")
            with lock:
                log.write(tag + line)
                log.flush()
                try:
                    stream.write(text)
                    stream.flush()
                except (OSError, ValueError):
                    pass
            if keep:
                kept.append(text)
        pipe.close()

    pumps = [threading.Thread(target=pump, args=(proc.stdout, out, b"", keep_stdout), daemon=True),
             threading.Thread(target=pump, args=(proc.stderr, err, b"! ", False), daemon=True)]
    for t in pumps:
        t.start()

    stopped_by: list = []

    def stop_group(signum, _frame):
        stopped_by.append(signal.Signals(signum).name)
        _signal_group(proc, signal.SIGTERM)

    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, stop_group)
    try:
        try:
            exit_code = proc.wait(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            _signal_group(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                _signal_group(proc, signal.SIGKILL)
                proc.wait()
            exit_code = EXIT_TIMEOUT
        if stopped_by and not timed_out:
            try:
                # launchd SIGKILLs this process 20s after its SIGTERM (ExitTimeOut): finish inside that.
                proc.wait(timeout=min(grace_s, LAUNCHD_STOP_GRACE_S))
            except subprocess.TimeoutExpired:
                _signal_group(proc, signal.SIGKILL)
                proc.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    for t in pumps:
        t.join(timeout=5)

    stdout = "".join(kept)
    if timed_out:
        return Execution("timeout", EXIT_TIMEOUT, f"timed out after {timeout_s}s", stdout)
    if stopped_by:
        return Execution("failed", exit_code if exit_code > 0 else 128 - exit_code,
                         f"stopped by {stopped_by[0]}", stdout)
    if exit_code != 0:
        # A negative code is a signal from outside the group (e.g. the OOM killer).
        reason = f"killed by signal {-exit_code}" if exit_code < 0 else f"exit code {exit_code}"
        return Execution("failed", 128 - exit_code if exit_code < 0 else exit_code, reason, stdout)
    return Execution("ok", 0, None, stdout)


def _signal_group(proc, sig) -> None:
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _prune_run_logs(log_dir: Path, keep_days: int = RUN_LOG_DAYS) -> None:
    """Delete run logs older than ``keep_days``; at most once an hour, so it costs nothing per run."""
    marker = log_dir / ".pruned"
    try:
        if marker.exists() and time.time() - marker.stat().st_mtime < 3600:
            return
        marker.touch()
        cutoff = time.time() - keep_days * 86400
        for path in log_dir.glob("*.log"):
            if path.stat().st_mtime < cutoff:
                path.unlink()
    except OSError:
        pass


def _fallback_record(state_dir: Path, record: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    with open(state_dir / "ledger_fallback.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")


def _refusal(registry: Registry, job: Job, ledger) -> Optional[str]:
    """Why this job may not start, or None. Budget is checked last: it needs the ledger."""
    harness = registry.harnesses[job.harness]
    if not job.enabled:
        return "job is disabled in the registry"
    if job.hermes_cron:
        return "fired by Hermes cron, not by omni run (Omni only records it)"
    missing = adapters.unavailable(harness)
    if missing:
        return missing
    workdir = job_workdir(registry, job)
    if not workdir.is_dir():
        return f"workdir does not exist: {workdir}"
    if job.monthly_usd is not None:
        unknown = ledger.month_unknown(job.name)
        if unknown:
            return (f"{unknown} run(s) this month have unknown cost, so the "
                    f"${job.monthly_usd:.2f} monthly cap cannot be enforced")
        spent = ledger.month_spend(job.name)
        if spent >= job.monthly_usd:
            return f"monthly budget reached: ${spent:.4f} spent of ${job.monthly_usd:.2f}"
    return None


def run(registry: Registry, job_name: str, ledger, *, state_dir: Path = STATE_DIR,
        rules_path: Path = RULES_PATH, out=sys.stdout, err=sys.stderr) -> Result:
    job = registry.job(job_name)
    harness = registry.harnesses[job.harness]
    is_script = harness.kind == "script"
    common = dict(job=job.name, domain=job.domain, harness=job.harness, model=job.model,
                  registry_sha=registry.sha)

    ledger_up = True
    try:
        reason = _refusal(registry, job, ledger)
        if reason:
            run_id = ledger.refuse(reason=reason, **common)
            return Result(status="refused", exit_code=EXIT_REFUSED, run_id=run_id, reason=reason)
    except LedgerError as exc:
        if not is_script:
            return Result(status="refused", exit_code=EXIT_NO_LEDGER,
                          reason=f"ledger unavailable, agent job not started: {exc}")
        ledger_up = False
        print(f"omni: ledger unavailable ({exc}); running script job and recording locally",
              file=sys.stderr)

    prompt = compose_prompt(job, rules_path)
    log_dir = state_dir / "runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{time.strftime('%Y%m%dT%H%M%S')}-{job.name}-{os.getpid()}.log"

    run_id = None
    if ledger_up:
        try:
            run_id = ledger.start(log_path=str(log_path), **common)
        except LedgerError as exc:
            if not is_script:
                return Result(status="refused", exit_code=EXIT_NO_LEDGER,
                              reason=f"ledger unavailable, agent job not started: {exc}")
            ledger_up = False

    _prune_run_logs(log_dir)
    with tempfile.TemporaryDirectory(prefix="omni-run-") as scratch:
        inv = adapters.build(harness, job, prompt, Path(scratch))
        with open(log_path, "wb") as log:
            log.write(f"$ {job.name} ({job.harness})\n".encode())
            ex = execute(inv.argv, cwd=job_workdir(registry, job), timeout_s=job.timeout_s, log=log,
                         out=out, err=err, keep_stdout=not is_script, env=inv.env)
        status, exit_code, reason = ex.status, ex.exit_code, ex.reason
        used = adapters.usage(harness, inv, ex.stdout)

    record = dict(status=status, exit_code=exit_code, reason=reason, cost_usd=used.cost_usd,
                  cost_source=used.cost_source, tokens_in=used.tokens_in,
                  tokens_out=used.tokens_out, model=used.model)
    if ledger_up:
        try:
            ledger.finish(run_id, **record)
        except LedgerError as exc:
            ledger_up = False
            print(f"omni: could not record run {run_id} in the ledger: {exc}", file=sys.stderr)
    if not ledger_up:
        _fallback_record(state_dir, {**common, **record, "run_id": run_id, "log_path": str(log_path),
                                     "ended_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    return Result(status=status, exit_code=exit_code, run_id=run_id, reason=reason,
                  cost_usd=used.cost_usd, log_path=log_path)
