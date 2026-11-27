"""One adapter per harness: how to invoke it headless, and how to read back what the run cost.

Every shape here was checked against a real run on this host (2026-11-14):
``hermes --usage-file`` writes ``estimated_cost_usd`` / ``input_tokens`` / ``output_tokens``;
``opencode run --format json`` emits ``step_finish`` events carrying ``part.cost`` and
``part.tokens``; ``pi -p --mode json`` (1.5.2) emits assistant ``message_end`` events carrying
``message.usage.cost.total``.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .registry import Harness, Job


@dataclass
class Invocation:
    argv: list
    usage_file: Optional[Path] = None
    env: dict = field(default_factory=dict)     # added to the process environment


@dataclass
class Usage:
    cost_usd: Optional[float] = None
    cost_source: str = "unknown"
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    model: Optional[str] = None


def resolve_bin(harness: Harness) -> Optional[str]:
    """Absolute path of the harness binary, or None when it is not installed."""
    if harness.kind == "script":
        return None
    candidate = os.path.expanduser(harness.bin)
    if os.sep in candidate:
        return candidate if os.access(candidate, os.X_OK) else None
    return shutil.which(candidate)


def unavailable(harness: Harness) -> Optional[str]:
    """Why this harness cannot run here, or None when it can."""
    if harness.kind == "script":
        return None
    if resolve_bin(harness) is None:
        return f"harness {harness.name!r} is not installed ({harness.bin} not found)"
    return None


def build(harness: Harness, job: Job, prompt: Optional[str], scratch: Path) -> Invocation:
    if harness.kind == "script":
        # No shell runs between the registry and the process, so `~/` is expanded here. A script that
        # spends money (a decision-model panel, say) reports it by writing {"cost_usd": ...} to
        # $OMNI_USAGE_FILE (omnikit.usage does this), so its cost lands in the ledger like an agent's.
        usage_file = scratch / "script-usage.json"
        return Invocation(argv=[os.path.expanduser(a) if a.startswith("~/") else a for a in job.command],
                          usage_file=usage_file, env={"OMNI_USAGE_FILE": str(usage_file)})
    binary = resolve_bin(harness)
    if harness.kind == "hermes":
        usage_file = scratch / "hermes-usage.json"
        argv = [binary]
        if job.profile:
            argv += ["-p", job.profile]
        argv += ["-z", prompt, "--usage-file", str(usage_file)]
        if job.model:
            argv += ["-m", job.model]
        return Invocation(argv=argv, usage_file=usage_file)
    if harness.kind == "opencode":
        argv = [binary, "run", "--format", "json"]
        if job.model:
            argv += ["-m", job.model]
        if job.agent:
            argv += ["--agent", job.agent]
        return Invocation(argv=argv + [prompt])
    if harness.kind == "pi":
        # --approve: trust the job's workdir for this run. Without it a headless Pi silently skips the
        # project's skills (.agents/skills) and settings, since no one is there to answer the trust prompt.
        # Registering a job with a workdir is the owner's decision to trust that folder.
        argv = [binary, "-p", "--mode", "json", "--no-session", "--approve"]
        if job.model:
            argv += ["--provider", "openrouter", "--model", job.model]
        if job.tools is not None:
            argv += ["--tools", ",".join(job.tools)]
        return Invocation(argv=argv + [prompt])
    raise ValueError(f"no adapter for harness kind {harness.kind!r}")


def _int(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _hermes_usage(inv: Invocation) -> Usage:
    try:
        data = json.loads(inv.usage_file.read_text())
    except (OSError, ValueError, AttributeError):
        return Usage()
    cost = data.get("estimated_cost_usd")
    aux = (data.get("auxiliary") or {}).get("estimated_cost_usd")
    if not isinstance(cost, (int, float)) or isinstance(cost, bool):
        return Usage(model=data.get("model"))
    total = float(cost) + (float(aux) if isinstance(aux, (int, float)) and not isinstance(aux, bool) else 0.0)
    return Usage(cost_usd=total, cost_source="hermes_usage_file", tokens_in=_int(data.get("input_tokens")),
                 tokens_out=_int(data.get("output_tokens")), model=data.get("model"))


def _opencode_usage(stdout: str) -> Usage:
    cost, tokens_in, tokens_out, steps = 0.0, 0, 0, 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "step_finish":
            continue
        part = event.get("part") or {}
        step_cost = part.get("cost")
        if not isinstance(step_cost, (int, float)) or isinstance(step_cost, bool):
            return Usage()  # a step with no cost makes the total unknown, not smaller
        tokens = part.get("tokens") or {}
        cost += float(step_cost)
        tokens_in += _int(tokens.get("input")) or 0
        tokens_out += _int(tokens.get("output")) or 0
        steps += 1
    if not steps:
        return Usage()
    return Usage(cost_usd=cost, cost_source="opencode_events", tokens_in=tokens_in, tokens_out=tokens_out)


def _pi_usage(stdout: str) -> Usage:
    """Sum ``usage.cost.total`` over the assistant ``message_end`` events (``turn_end`` repeats them)."""
    cost, tokens_in, tokens_out, messages, model = 0.0, 0, 0, 0, None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        if message.get("role") != "assistant":
            continue
        used = message.get("usage") or {}
        total = (used.get("cost") or {}).get("total")
        if not isinstance(total, (int, float)) or isinstance(total, bool):
            return Usage()  # an assistant message with no cost makes the total unknown
        cost += float(total)
        tokens_in += _int(used.get("input")) or 0
        tokens_out += _int(used.get("output")) or 0
        model = message.get("model") or model
        messages += 1
    if not messages:
        return Usage()
    return Usage(cost_usd=cost, cost_source="pi_events", tokens_in=tokens_in, tokens_out=tokens_out,
                 model=model)


def _script_usage(inv: Invocation) -> Usage:
    try:
        data = json.loads(inv.usage_file.read_text()) if inv.usage_file else None
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("cost_usd"), (int, float)):
        return Usage(cost_usd=0.0, cost_source="none")
    return Usage(cost_usd=float(data["cost_usd"]), cost_source="script_usage_file",
                 tokens_in=_int(data.get("tokens_in")), tokens_out=_int(data.get("tokens_out")),
                 model=data.get("model"))


def usage(harness: Harness, inv: Invocation, stdout: str) -> Usage:
    if harness.kind == "script":
        return _script_usage(inv)
    if harness.kind == "hermes":
        return _hermes_usage(inv)
    if harness.kind == "opencode":
        return _opencode_usage(stdout)
    if harness.kind == "pi":
        return _pi_usage(stdout)
    return Usage()
