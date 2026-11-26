"""Load and validate ``registry.yaml``: the one file that binds a job to a harness and a model.

Validation is strict on purpose. An unknown key is an error, not a silently ignored typo: a
misspelt ``monthly_usd`` would otherwise run a job with no budget at all.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

CORE_DIR = Path(__file__).resolve().parents[1]
REAL_PATH = CORE_DIR / "registry.yaml"          # this machine's registry (instance branch; not on main)
EXAMPLE_PATH = CORE_DIR / "registry.example.yaml"  # the Omni OS base registry: Atma only


def default_path() -> Path:
    """This machine's registry when it has one, else the base example a fresh Omni OS checkout runs."""
    return REAL_PATH if REAL_PATH.exists() else EXAMPLE_PATH


DEFAULT_PATH = default_path()

HARNESS_KINDS = ("script", "hermes", "opencode", "pi")
DEFAULT_TIMEOUT_S = 600

_HARNESS_KEYS = {"kind", "bin"}
_DOMAIN_KEYS = {"workdir"}
_JOB_KEYS = {"domain", "harness", "enabled", "command", "prompt", "prompt_file", "model", "profile",
             "agent", "tools", "timeout_s", "monthly_usd", "rules", "schedule", "launchd", "log", "workdir", "hermes_cron"}
_SERVICE_KEYS = {"domain", "launchd", "port"}
_PLAN_KEYS = {"description", "stages"}
_STAGE_KEYS = {"name", "jobs", "needs"}


class RegistryError(ValueError):
    """The registry file is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class Harness:
    name: str
    kind: str
    bin: Optional[str] = None


@dataclass(frozen=True)
class Domain:
    name: str
    workdir: Path


@dataclass(frozen=True)
class Job:
    name: str
    domain: str
    harness: str
    enabled: bool = True
    command: Optional[tuple] = None      # script jobs
    prompt: Optional[str] = None         # agent jobs (inline, or read from prompt_file at load)
    model: Optional[str] = None
    profile: Optional[str] = None        # hermes profile
    agent: Optional[str] = None          # opencode agent
    tools: Optional[tuple] = None        # pi tool allowlist
    timeout_s: int = DEFAULT_TIMEOUT_S
    monthly_usd: Optional[float] = None  # cap on this job's spend per calendar month; None = no cap
    rules: bool = True                   # prepend rules/GLOBAL.md to the prompt
    schedule: object = None              # str or tuple of str; see schedule.py. Becomes the plist's timer
    launchd: Optional[str] = None        # the launchd label that fires it today
    log: Optional[str] = None            # where it really logs, when not the plist's path; may glob
    workdir: Optional[Path] = None       # cwd for this job, when not its domain's workdir
    hermes_cron: Optional[str] = None    # Hermes cron job id: Hermes fires it, Omni watches and records it


@dataclass(frozen=True)
class Service:
    """A long-running process launchd keeps alive. The runner never starts one; `omni status` watches it."""
    name: str
    domain: str
    launchd: str
    port: Optional[int] = None


@dataclass(frozen=True)
class Stage:
    """Jobs that do one step of a plan together. ``needs`` names the stages that must run first."""
    name: str
    jobs: tuple
    needs: tuple = ()


@dataclass(frozen=True)
class Plan:
    """A named group of jobs in dependency order: what `omni plan` and the system page draw."""
    name: str
    description: str
    stages: tuple


@dataclass(frozen=True)
class Registry:
    path: Path
    sha: str
    harnesses: dict
    domains: dict
    jobs: dict
    services: dict
    plans: dict
    readiness: object = None             # readiness.Spec, or None

    def job(self, name: str) -> Job:
        if name not in self.jobs:
            raise RegistryError(f"unknown job {name!r}; known: {', '.join(sorted(self.jobs)) or '(none)'}")
        return self.jobs[name]


def _mapping(value, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RegistryError(f"{where} must be a mapping")
    for key in value:
        # YAML reads bare `off`, `on`, `yes`, `no` as booleans: a job called `off` would vanish.
        if not isinstance(key, str):
            raise RegistryError(f"{where}: name {key!r} is not a string; quote it in the YAML")
    return value


def _unknown_keys(entry: dict, allowed: set, where: str) -> None:
    extra = sorted(set(entry) - allowed)
    if extra:
        raise RegistryError(f"{where}: unknown key(s) {extra}; allowed: {sorted(allowed)}")


def _harnesses(raw: dict) -> dict:
    out = {}
    for name, entry in raw.items():
        entry = _mapping(entry, f"harnesses.{name}")
        _unknown_keys(entry, _HARNESS_KEYS, f"harnesses.{name}")
        kind = entry.get("kind")
        if kind not in HARNESS_KINDS:
            raise RegistryError(f"harnesses.{name}.kind must be one of {HARNESS_KINDS}, got {kind!r}")
        if kind != "script" and not entry.get("bin"):
            raise RegistryError(f"harnesses.{name}: a {kind} harness needs `bin`")
        out[name] = Harness(name=name, kind=kind, bin=entry.get("bin"))
    return out


def _domains(raw: dict) -> dict:
    out = {}
    for name, entry in raw.items():
        entry = _mapping(entry, f"domains.{name}")
        _unknown_keys(entry, _DOMAIN_KEYS, f"domains.{name}")
        if not entry.get("workdir"):
            raise RegistryError(f"domains.{name}: `workdir` is required")
        out[name] = Domain(name=name, workdir=Path(str(entry["workdir"])).expanduser())
    return out


def _job(name: str, entry: dict, harnesses: dict, domains: dict, base: Path) -> Job:
    where = f"jobs.{name}"
    entry = _mapping(entry, where)
    _unknown_keys(entry, _JOB_KEYS, where)
    for key in ("domain", "harness"):
        if not entry.get(key):
            raise RegistryError(f"{where}: `{key}` is required")
    if entry["domain"] not in domains:
        raise RegistryError(f"{where}: unknown domain {entry['domain']!r}")
    if entry["harness"] not in harnesses:
        raise RegistryError(f"{where}: unknown harness {entry['harness']!r}")
    kind = harnesses[entry["harness"]].kind

    command, prompt = entry.get("command"), entry.get("prompt")
    if entry.get("prompt_file"):
        if prompt:
            raise RegistryError(f"{where}: give `prompt` or `prompt_file`, not both")
        prompt_path = (base / str(entry["prompt_file"])).expanduser()
        if not prompt_path.is_file():
            raise RegistryError(f"{where}: prompt_file not found: {prompt_path}")
        prompt = prompt_path.read_text()
    if entry.get("hermes_cron"):
        if kind != "hermes":
            raise RegistryError(f"{where}: `hermes_cron` jobs must use a hermes harness")
        if command or prompt or entry.get("launchd"):
            raise RegistryError(f"{where}: a `hermes_cron` job is defined in Hermes; give no "
                                "command, prompt or launchd label here")
    elif kind == "script":
        if not (isinstance(command, list) and command and all(isinstance(a, str) for a in command)):
            raise RegistryError(f"{where}: a script job needs `command` as a non-empty list of strings")
        if prompt or entry.get("model"):
            raise RegistryError(f"{where}: a script job takes no prompt or model")
    else:
        if command:
            raise RegistryError(f"{where}: `command` is only for script jobs")
        if not (isinstance(prompt, str) and prompt.strip()):
            raise RegistryError(f"{where}: a {kind} job needs `prompt` or `prompt_file`")

    timeout_s = entry.get("timeout_s", DEFAULT_TIMEOUT_S)
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or timeout_s <= 0:
        raise RegistryError(f"{where}: timeout_s must be a positive integer")
    cap = entry.get("monthly_usd")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap < 0):
        raise RegistryError(f"{where}: monthly_usd must be a number >= 0")
    tools = entry.get("tools")
    if tools is not None and not (isinstance(tools, list) and all(isinstance(t, str) for t in tools)):
        raise RegistryError(f"{where}: tools must be a list of strings")
    for key in ("enabled", "rules"):
        if key in entry and not isinstance(entry[key], bool):
            raise RegistryError(f"{where}: {key} must be true or false")

    sched = entry.get("schedule")
    if sched is not None:
        from .schedule import ScheduleError, to_launchd
        try:
            to_launchd(sched)
        except ScheduleError as exc:
            raise RegistryError(f"{where}: schedule: {exc}") from exc
        if isinstance(sched, list):
            sched = tuple(sched)
    if entry.get("launchd") and entry.get("enabled", True) and sched is None:
        raise RegistryError(f"{where}: a job launchd fires needs a `schedule`")

    return Job(
        name=name, domain=entry["domain"], harness=entry["harness"],
        enabled=entry.get("enabled", True),
        command=tuple(command) if command else None, prompt=prompt,
        model=entry.get("model"), profile=entry.get("profile"), agent=entry.get("agent"),
        tools=tuple(tools) if tools is not None else None,
        timeout_s=timeout_s, monthly_usd=None if cap is None else float(cap),
        rules=entry.get("rules", True), schedule=sched, launchd=entry.get("launchd"),
        log=entry.get("log"),
        workdir=Path(str(entry["workdir"])).expanduser() if entry.get("workdir") else None,
        hermes_cron=str(entry["hermes_cron"]) if entry.get("hermes_cron") else None,
    )


def _services(raw: dict, domains: dict) -> dict:
    out = {}
    for name, entry in raw.items():
        where = f"services.{name}"
        entry = _mapping(entry, where)
        _unknown_keys(entry, _SERVICE_KEYS, where)
        if entry.get("domain") not in domains:
            raise RegistryError(f"{where}: unknown domain {entry.get('domain')!r}")
        if not isinstance(entry.get("launchd"), str) or not entry["launchd"]:
            raise RegistryError(f"{where}: `launchd` (the label that keeps it alive) is required")
        port = entry.get("port")
        if port is not None and (isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536):
            raise RegistryError(f"{where}: port must be an integer between 1 and 65535")
        out[name] = Service(name=name, domain=entry["domain"], launchd=entry["launchd"], port=port)
    return out


def _readiness(raw, domains: dict, base: Path):
    from .readiness import ReadinessError, parse
    try:
        return parse(raw, domains, base)
    except ReadinessError as exc:
        raise RegistryError(str(exc)) from exc


def _plans(raw: dict, jobs: dict) -> dict:
    out = {}
    for name, entry in raw.items():
        where = f"plans.{name}"
        entry = _mapping(entry, where)
        _unknown_keys(entry, _PLAN_KEYS, where)
        stages_raw = entry.get("stages")
        if not isinstance(stages_raw, list) or not stages_raw:
            raise RegistryError(f"{where}: `stages` must be a non-empty list")
        stages, seen = [], set()
        for i, stage in enumerate(stages_raw):
            swhere = f"{where}.stages[{i}]"
            stage = _mapping(stage, swhere)
            _unknown_keys(stage, _STAGE_KEYS, swhere)
            sname = stage.get("name")
            if not isinstance(sname, str) or not sname:
                raise RegistryError(f"{swhere}: `name` is required")
            if sname in seen:
                raise RegistryError(f"{swhere}: duplicate stage name {sname!r}")
            sjobs = stage.get("jobs")
            if not isinstance(sjobs, list) or not sjobs:
                raise RegistryError(f"{swhere}: `jobs` must be a non-empty list")
            for job in sjobs:
                if job not in jobs:
                    raise RegistryError(f"{swhere}: unknown job {job!r}")
            needs = stage.get("needs") or []
            if not isinstance(needs, list):
                raise RegistryError(f"{swhere}: `needs` must be a list of stage names")
            for need in needs:
                # A stage may only need one defined above it, so a plan cannot contain a cycle.
                if need not in seen:
                    raise RegistryError(f"{swhere}: needs {need!r}, which is not an earlier stage")
            seen.add(sname)
            stages.append(Stage(name=sname, jobs=tuple(sjobs), needs=tuple(needs)))
        out[name] = Plan(name=name, description=str(entry.get("description") or ""), stages=tuple(stages))
    return out


def load(path: Optional[Path] = None) -> Registry:
    path = Path(path) if path else default_path()
    try:
        text = path.read_text()
    except OSError as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"registry {path} is not valid YAML: {exc}") from exc
    raw = _mapping(raw, "registry")
    _unknown_keys(raw, {"version", "harnesses", "domains", "jobs", "services", "plans", "readiness"}, "registry")
    if raw.get("version") != 1:
        raise RegistryError(f"registry version must be 1, got {raw.get('version')!r}")

    harnesses = _harnesses(_mapping(raw.get("harnesses"), "harnesses"))
    domains = _domains(_mapping(raw.get("domains"), "domains"))
    jobs = {name: _job(name, entry, harnesses, domains, path.parent)
            for name, entry in _mapping(raw.get("jobs"), "jobs").items()}
    return Registry(path=path, sha=hashlib.sha256(text.encode()).hexdigest()[:12],
                    harnesses=harnesses, domains=domains, jobs=jobs,
                    services=_services(_mapping(raw.get("services"), "services"), domains),
                    plans=_plans(_mapping(raw.get("plans"), "plans"), jobs),
                    readiness=_readiness(raw.get("readiness"), domains, path.parent))
