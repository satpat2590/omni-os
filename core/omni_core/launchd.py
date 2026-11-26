"""launchd plists generated from the registry: the registry says what runs when, launchd fires it.

Every scheduled job's plist runs

    omni-svc  omni-job JOB  --  COMMAND...

``omni-svc`` loads the secrets, ``omni-job`` runs the job through ``omni run`` (ledger row, budget,
timeout, global rules) and, if Omni itself cannot start (broken venv, unreadable registry), runs
COMMAND directly so a feed never stops because the platform around it broke. Agent jobs get no
fallback: without the ledger their spend could not be capped.

An existing plist keeps its environment, log paths, user and group; only the program, the schedule
and the working directory are rewritten. A job with no plist yet gets one from the template.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from . import schedule
from .registry import CORE_DIR, Job, Registry

PLIST_DIR = Path("/Library/LaunchDaemons")
HOME = Path.home()
# The wrapper that loads this machine's secrets: $OMNI_SVC, else ~/bin/omni-svc, else the one core ships.
OMNI_SVC = Path(os.environ.get("OMNI_SVC") or (
    HOME / "bin" / "omni-svc" if (HOME / "bin" / "omni-svc").exists() else CORE_DIR / "bin" / "omni-svc"))
OMNI_JOB = CORE_DIR / "bin" / "omni-job"
LOG_DIR = CORE_DIR / "state" / "logs"
BACKUP_DIR = CORE_DIR / "state" / "launchd-backup"
DEFAULT_PATH = ":".join([str(CORE_DIR / ".venv/bin"), str(HOME / ".local/bin"), "/opt/homebrew/bin",
                         "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
SCHEDULE_KEYS = ("StartInterval", "StartCalendarInterval")


class LaunchdError(RuntimeError):
    pass


def program(job: Job) -> list:
    argv = [str(OMNI_SVC), str(OMNI_JOB), job.name]
    if job.command:
        argv += ["--"] + [str(HOME / a[2:]) if a.startswith("~/") else a for a in job.command]
    return argv


def template(job: Job) -> dict:
    log = str(LOG_DIR / f"{job.name}.log")
    return {"Label": job.launchd, "UserName": HOME.name, "GroupName": "staff",
            "EnvironmentVariables": {"HOME": str(HOME), "USER": HOME.name, "LOGNAME": HOME.name,
                                     "LANG": "en_US.UTF-8", "PATH": DEFAULT_PATH},
            "StandardOutPath": log, "StandardErrorPath": log}


def render(registry: Registry, job: Job, existing: Optional[dict]) -> dict:
    if not job.launchd or not job.schedule:
        raise LaunchdError(f"{job.name}: needs both `launchd` and `schedule` to have a plist")
    plist = dict(existing) if existing else template(job)
    plist["Label"] = job.launchd
    plist["ProgramArguments"] = program(job)
    plist["WorkingDirectory"] = str(job.workdir or registry.domains[job.domain].workdir)
    for key in SCHEDULE_KEYS:
        plist.pop(key, None)
    plist.update(schedule.to_launchd(job.schedule))
    plist.pop("RunAtLoad", None)        # a reload must not fire a trade decision out of schedule
    return plist


def read(label: str, plist_dir: Path = PLIST_DIR) -> Optional[dict]:
    try:
        with open(plist_dir / f"{label}.plist", "rb") as f:
            return plistlib.load(f)
    except FileNotFoundError:
        return None


def owner(plist: Optional[dict]) -> Optional[str]:
    """The user a plist runs as, when it is not this user. /Library/LaunchDaemons is shared by every
    account on the machine, so two Omni installs (an instance and a testing ground) can collide on a
    label; neither may rewrite the other's."""
    user = (plist or {}).get("UserName")
    return user if user and user != HOME.name else None


def diff(current: Optional[dict], wanted: dict) -> list:
    """Human-readable lines for each top-level key that differs."""
    if current is None:
        return ["(no plist yet: will be created)"]
    lines = []
    for key in sorted(set(current) | set(wanted)):
        if current.get(key) != wanted.get(key):
            lines.append(f"{key}: {current.get(key)!r} -> {wanted.get(key)!r}")
    return lines


def is_running(label: str) -> bool:
    proc = subprocess.run(["launchctl", "print", f"system/{label}"], capture_output=True, text=True)
    return proc.returncode == 0 and "\tstate = running" in proc.stdout


def _sudo(*argv, check=True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["sudo", "-n", *argv], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise LaunchdError(f"{' '.join(argv)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def apply(registry: Registry, job: Job, *, wait_s: int = 900, interrupt: bool = False,
          plist_dir: Path = PLIST_DIR, running: Callable[[str], bool] = is_running, log=print) -> str:
    """Write the job's plist and reload it in launchd. Returns what happened.

    A reload stops a running job (launchd sends it SIGTERM), so this waits up to ``wait_s`` for
    the job to be idle and checks again right before reloading. ``interrupt`` reloads anyway once
    the wait is over: only for jobs that resume safely, such as a collector whose cursor moves
    only after its items are stored. The old plist is kept in ``state/launchd-backup``.
    """
    current = read(job.launchd, plist_dir)
    other = owner(current)
    if other:
        raise LaunchdError(f"{job.launchd}: that plist runs as {other}, not {HOME.name}; refusing to "
                           f"rewrite another user's job (give this registry its own launchd labels)")
    wanted = render(registry, job, current)
    if current == wanted:
        return "unchanged"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", suffix=".plist", delete=False) as tmp:
        plistlib.dump(wanted, tmp)
    try:
        lint = subprocess.run(["plutil", "-lint", tmp.name], capture_output=True, text=True)
        if lint.returncode != 0:
            raise LaunchdError(f"{job.launchd}: rendered plist is invalid: {lint.stdout.strip()}")
        deadline = time.time() + wait_s
        while running(job.launchd):
            if time.time() > deadline:
                if interrupt:
                    log(f"{job.name}: still running after {wait_s}s; interrupting it (--interrupt)")
                    break
                return f"skipped: still running after {wait_s}s; nothing changed"
            time.sleep(5)
        target = plist_dir / f"{job.launchd}.plist"
        if current is not None:
            stamp = time.strftime("%Y%m%dT%H%M%S")
            with open(BACKUP_DIR / f"{job.launchd}.{stamp}.plist", "wb") as f:
                plistlib.dump(current, f)
        _sudo("install", "-m", "644", "-o", "root", "-g", "wheel", tmp.name, str(target))
        if running(job.launchd) and not interrupt:
            log(f"{job.name}: started while the plist was written; waiting for it before the reload")
            while running(job.launchd):
                if time.time() > deadline + 600:
                    return "written but not reloaded: job is still running; reload it by hand"
                time.sleep(5)
        _sudo("launchctl", "bootout", f"system/{job.launchd}", check=False)
        _sudo("launchctl", "bootstrap", "system", str(target))
        check = subprocess.run(["launchctl", "print", f"system/{job.launchd}"], capture_output=True)
        if check.returncode != 0:
            raise LaunchdError(f"{job.launchd}: not loaded after bootstrap")
        return "created" if current is None else "updated"
    finally:
        os.unlink(tmp.name)
