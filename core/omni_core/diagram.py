"""Mermaid diagrams generated from the registry, optionally coloured by what each job last did.

Nothing here is drawn by hand. ``plan_mermaid`` turns a plan's stages into a flowchart (one box
per job, one subgraph per stage, one arrow per ``needs``); ``system_mermaid`` draws a domain's
services and plans. With ``states`` the boxes carry a status word and colour; without it the
output is the bare structure, which is what gets written to the repo so the file only changes
when the system does.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from . import jobstate, schedule
from .registry import Plan, Registry

# Light fills with dark text read on both a light and a dark page. The status word is always in
# the label too, so colour is never the only signal.
CLASS_DEFS = """
  classDef ok fill:#E1F5EE,stroke:#0F6E56,color:#04342C
  classDef overdue fill:#FAEEDA,stroke:#854F0B,color:#412402
  classDef failed fill:#FCEBEB,stroke:#A32D2D,color:#501313
  classDef waiting fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A
  classDef unknown fill:#F1EFE8,stroke:#5F5E5A,color:#2C2C2A,stroke-dasharray:4 3
""".rstrip("\n")


def _id(prefix: str, name: str) -> str:
    return prefix + re.sub(r"[^A-Za-z0-9]", "_", name)


def _label(text: str) -> str:
    return text.replace('"', "'")


def plan_mermaid(registry: Registry, plan: Plan, states: Optional[dict] = None,
                 now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    lines = ["flowchart TD"]
    for i, stage in enumerate(plan.stages):
        lines.append(f'  subgraph s{i}["{_label(stage.name)}"]')
        for name in stage.jobs:
            job = registry.jobs[name]
            parts = [name]
            suffix = ""
            if states is not None:
                state = states[name]
                seen = "" if state.last_activity is None else f", {jobstate.ago(now - state.last_activity)} ago"
                parts.append(f"{state.status}{seen}")
                suffix = f":::{state.status}"
            elif job.schedule:
                parts.append(schedule.describe(job.schedule))
            lines.append(f'    {_id("j_", name)}["{_label("<br/>".join(parts))}"]{suffix}')
        lines.append("  end")
    index = {stage.name: i for i, stage in enumerate(plan.stages)}
    for i, stage in enumerate(plan.stages):
        for need in stage.needs:
            lines.append(f"  s{index[need]} --> s{i}")
    if states is not None:
        lines.append(CLASS_DEFS)
    return "\n".join(lines)


def system_mermaid(registry: Registry, service_states: Optional[list] = None) -> str:
    """Every domain with its services and the plans its jobs belong to."""
    up = {s.name: s.ok for s in service_states} if service_states is not None else None
    lines = ["flowchart LR"]
    domains = sorted({s.domain for s in registry.services.values()} | {j.domain for j in registry.jobs.values()})
    for domain in domains:
        services = [s for s in registry.services.values() if s.domain == domain]
        jobs = [j for j in registry.jobs.values() if j.domain == domain]
        lines.append(f'  subgraph {_id("d_", domain)}["{_label(domain)}"]')
        for service in sorted(services, key=lambda s: s.name):
            port = f"<br/>port {service.port}" if service.port else ""
            suffix = "" if up is None else (":::ok" if up.get(service.name) else ":::failed")
            lines.append(f'    {_id("sv_", service.name)}(["{_label(service.name + port)}"]){suffix}')
        if jobs:
            noun = "job" if len(jobs) == 1 else "jobs"
            lines.append(f'    {_id("jobs_", domain)}["{len(jobs)} scheduled {noun}"]')
        lines.append("  end")
    if up is not None:
        lines.append(CLASS_DEFS)
    return "\n".join(lines)


def snapshot(registry: Registry, states: dict, service_states: list, now: Optional[float] = None) -> dict:
    """Everything the system page shows, as plain data."""
    now = time.time() if now is None else now

    def job_row(name: str) -> dict:
        job, state = registry.jobs[name], states[name]
        return {"name": name, "domain": job.domain, "harness": job.harness, "schedule": schedule.describe(job.schedule),
                "status": state.status, "detail": state.detail, "fired_by": state.fired_by,
                "last_activity": state.last_activity}

    planned = set()
    plans = []
    for plan in registry.plans.values():
        stages = []
        for stage in plan.stages:
            planned.update(stage.jobs)
            stages.append({"name": stage.name, "needs": list(stage.needs),
                           "status": jobstate.worst(states[j].status for j in stage.jobs),
                           "jobs": [job_row(j) for j in stage.jobs]})
        plans.append({"name": plan.name, "description": plan.description,
                      "status": jobstate.worst(s["status"] for s in stages), "stages": stages,
                      "mermaid": plan_mermaid(registry, plan, states, now)})
    others: dict = {}
    for job in registry.jobs.values():
        if job.name not in planned:
            others.setdefault(job.domain, []).append(job_row(job.name))
    return {
        "generated_at": now, "registry_sha": registry.sha,
        "services": [{"name": s.name, "domain": s.domain, "state": s.state, "port": s.port,
                      "port_open": s.port_open, "ok": s.ok}
                     for s in sorted(service_states, key=lambda s: (s.domain, s.name))],
        "system_mermaid": system_mermaid(registry, service_states),
        "plans": plans,
        "other_jobs": [{"domain": d, "jobs": sorted(rows, key=lambda r: r["name"])}
                       for d, rows in sorted(others.items())],
        "counts": {status: sum(1 for s in states.values() if s.status == status)
                   for status in jobstate.SEVERITY},
    }


def markdown(registry: Registry) -> str:
    """The structure-only document for the repo: it changes only when the registry does."""
    out = ["# Omni system map", "",
           "Generated by `omni diagram --write` from `core/registry.yaml`. Do not edit by hand.",
           "Live status is on the dashboard's system page; this file is the structure only.", "",
           "## Domains and services", "", "```mermaid", system_mermaid(registry), "```", ""]
    for plan in registry.plans.values():
        out += [f"## Plan: {plan.name}", "", plan.description, "", "```mermaid",
                plan_mermaid(registry, plan), "```", ""]
    return "\n".join(out)


def write_docs(registry: Registry, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SYSTEM.md"
    path.write_text(markdown(registry))
    return path
