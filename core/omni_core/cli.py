"""``omni``: the command launchd (or you) calls to run a registered job.

    omni list                 every job with its harness, model and cap
    omni check                validate the registry, harness binaries, workdirs and the ledger
    omni status               is every service up, and who fires each job today
    omni plan [NAME]          each plan's stages and what every job in them last did
    omni diagram [--write]    Mermaid for the system map and every plan; --write saves docs/SYSTEM.md
    omni run JOB [--dry-run]  run one job through its harness and record it
    omni spend [--days N]     spend and failures per job from the ledger
    omni ready                is Omni keeping Edoras and Itihasa alive? exit 0 only if every check passes
    omni hermes-sync          copy finished Hermes cron runs (tokens, cost) into the ledger
    omni launchd diff [JOB..] what the generated plists would change (all scheduled jobs by default)
    omni launchd apply JOB..  write those plists and reload them (needs sudo; waits for idle jobs)
    omni migrate              create or update the ledger tables
"""
from __future__ import annotations

import argparse
import shlex
import sys
import tempfile
from pathlib import Path

from . import adapters, diagram, hermes_cron, jobstate, launchd, readiness, runner, schedule, status
from .ledger import Ledger, LedgerError
from .registry import CORE_DIR, RegistryError, load

CORE_DOCS = CORE_DIR / "docs"


def _list(registry) -> int:
    for job in registry.jobs.values():
        cap = "no cap" if job.monthly_usd is None else f"${job.monthly_usd:.2f}/mo"
        if job.enabled:
            state = f"  [launchd -> omni: {schedule.describe(job.schedule)}]" if job.launchd else ""
        else:
            state = "  [launchd direct]" if job.launchd else "  [disabled]"
        print(f"{job.name:<24} {job.domain:<10} {job.harness:<9} {job.model or '-':<46} {cap}{state}")
    return 0


def _check(registry, ledger) -> int:
    problems = []
    print(f"registry {registry.path} (sha {registry.sha}): {len(registry.jobs)} jobs, "
          f"{len(registry.harnesses)} harnesses, {len(registry.domains)} domains")
    for harness in registry.harnesses.values():
        missing = adapters.unavailable(harness)
        users = [j.name for j in registry.jobs.values() if j.harness == harness.name and j.enabled]
        print(f"  harness {harness.name:<9} {'MISSING' if missing else 'ok'}")
        if missing and users:
            problems.append(f"{missing}; its jobs will be refused: {', '.join(users)}")
    for domain in registry.domains.values():
        if not domain.workdir.is_dir():
            problems.append(f"domain {domain.name!r}: workdir does not exist: {domain.workdir}")
    scheduled = _scheduled(registry, [])
    foreign = [j.name for j in scheduled if launchd.owner(launchd.read(j.launchd))]
    drifted = [j.name for j in scheduled if j.name not in foreign
               and launchd.render(registry, j, launchd.read(j.launchd)) != launchd.read(j.launchd)]
    if foreign:
        problems.append(f"{len(foreign)} launchd label(s) belong to another user on this machine "
                        "(give this registry its own labels): " + ", ".join(foreign))
    if drifted:
        problems.append(f"{len(drifted)} plist(s) differ from the registry (omni launchd diff): "
                        + ", ".join(drifted))
    if not runner.RULES_PATH.is_file():
        problems.append(f"global rules missing: {runner.RULES_PATH}")
    try:
        ledger.ping()
        print("  ledger    ok")
    except LedgerError as exc:
        problems.append(str(exc))
    for problem in problems:
        print(f"PROBLEM: {problem}")
    return 1 if problems else 0


def _run(registry, ledger, name: str, dry_run: bool) -> int:
    if dry_run:
        job = registry.job(name)
        harness = registry.harnesses[job.harness]
        missing = adapters.unavailable(harness)
        if missing:
            print(f"would be refused: {missing}")
            return runner.EXIT_REFUSED
        with tempfile.TemporaryDirectory() as scratch:
            inv = adapters.build(harness, job, runner.compose_prompt(job), Path(scratch))
        print(f"cwd: {runner.job_workdir(registry, job)}")
        print("argv: " + " ".join(shlex.quote(a if len(a) < 80 else a[:77] + "...") for a in inv.argv))
        return 0
    result = runner.run(registry, name, ledger)
    cost = "unknown" if result.cost_usd is None else f"${result.cost_usd:.6f}"
    detail = f" ({result.reason})" if result.reason else ""
    print(f"omni: {name} {result.status}{detail}; run {result.run_id}, cost {cost}", file=sys.stderr)
    return result.exit_code


def _states(registry, ledger) -> dict:
    try:
        last_runs = ledger.last_runs()
    except LedgerError as exc:
        print(f"omni: ledger unavailable, jobs run through omni show as unknown: {exc}", file=sys.stderr)
        last_runs = {}
    return jobstate.job_states(registry, last_runs=last_runs)


def _plan(registry, ledger, name) -> int:
    if name and name not in registry.plans:
        raise RegistryError(f"unknown plan {name!r}; known: {', '.join(sorted(registry.plans)) or '(none)'}")
    states = _states(registry, ledger)
    worst = "ok"
    for plan in registry.plans.values():
        if name and plan.name != name:
            continue
        plan_status = jobstate.worst(states[j].status for stage in plan.stages for j in stage.jobs)
        worst = jobstate.worst([worst, plan_status])
        print(f"{plan.name}: {plan_status}  ({plan.description})")
        for stage in plan.stages:
            needs = f"  needs {', '.join(stage.needs)}" if stage.needs else ""
            print(f"  {stage.name}{needs}")
            for job in stage.jobs:
                state = states[job]
                print(f"    {state.status:<8} {job:<28} {state.detail}")
    return 1 if worst in ("failed", "overdue") else 0


def _diagram(registry, write: bool) -> int:
    if write:
        print(f"wrote {diagram.write_docs(registry, CORE_DOCS)}")
        return 0
    print(diagram.markdown(registry))
    return 0


def _spend(ledger, days: int) -> int:
    rows = ledger.spend(days)
    print(f"{'job':<24} {'harness':<9} {'runs':>5} {'failed':>6} {'unknown cost':>12} {'usd':>10}")
    for job, harness, runs, failed, unknown, usd in rows:
        print(f"{job:<24} {harness:<9} {runs:>5} {failed:>6} {unknown:>12} {usd:>10.4f}")
    print(f"total over {days}d: ${sum(r[5] for r in rows):.4f}")
    return 0


def _scheduled(registry, names) -> list:
    """Jobs whose plist the registry owns: enabled, with a launchd label and a schedule."""
    jobs = [registry.job(n) for n in names] if names else list(registry.jobs.values())
    owned = [j for j in jobs if j.enabled and j.launchd and j.schedule]
    for j in jobs:
        if names and j not in owned:
            raise RegistryError(f"{j.name}: not a scheduled job (needs enabled, launchd and schedule)")
    return owned


def _launchd(registry, action: str, names, wait_s: int, interrupt: bool = False) -> int:
    jobs = _scheduled(registry, names)
    if action == "diff":
        changed = 0
        for job in jobs:
            lines = launchd.diff(launchd.read(job.launchd), launchd.render(registry, job, launchd.read(job.launchd)))
            if lines:
                changed += 1
                print(f"{job.name} ({job.launchd})")
                for line in lines:
                    print(f"    {line}")
        print(f"{changed} of {len(jobs)} plist(s) would change")
        return 0
    if not names:
        raise RegistryError("name the jobs to apply; there is no apply-everything")
    failed = 0
    for job in jobs:
        try:
            outcome = launchd.apply(registry, job, wait_s=wait_s, interrupt=interrupt)
        except launchd.LaunchdError as exc:
            outcome, failed = f"FAILED: {exc}", failed + 1
        print(f"{job.name:<28} {outcome}", flush=True)
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="omni", description="Omni core: run registered jobs.")
    parser.add_argument("--registry", help="registry file (default: core/registry.yaml, else core/registry.example.yaml)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    sub.add_parser("status")
    plan_p = sub.add_parser("plan")
    plan_p.add_argument("name", nargs="?")
    diagram_p = sub.add_parser("diagram")
    diagram_p.add_argument("--write", action="store_true", help="save docs/SYSTEM.md")
    sub.add_parser("migrate")
    run_p = sub.add_parser("run")
    run_p.add_argument("job")
    run_p.add_argument("--dry-run", action="store_true", help="print what would run; start nothing")
    spend_p = sub.add_parser("spend")
    spend_p.add_argument("--days", type=int, default=30)
    sub.add_parser("hermes-sync")
    sub.add_parser("ready")
    launchd_p = sub.add_parser("launchd")
    launchd_p.add_argument("action", choices=["diff", "apply"])
    launchd_p.add_argument("jobs", nargs="*")
    launchd_p.add_argument("--wait", type=int, default=900, help="seconds to wait for a running job")
    launchd_p.add_argument("--interrupt", action="store_true",
                           help="reload a job still running after --wait (only for jobs that resume safely)")
    opts = parser.parse_args(argv)

    ledger = Ledger()
    try:
        if opts.cmd == "migrate":
            print("applied: " + ", ".join(ledger.migrate()))
            return 0
        if opts.cmd == "spend":
            return _spend(ledger, opts.days)
        registry = load(opts.registry)
        if opts.cmd == "list":
            return _list(registry)
        if opts.cmd == "check":
            return _check(registry, ledger)
        if opts.cmd == "status":
            lines, code = status.render(registry, status.service_states(registry))
            print("\n".join(lines))
            return code
        if opts.cmd == "plan":
            return _plan(registry, ledger, opts.name)
        if opts.cmd == "diagram":
            return _diagram(registry, opts.write)
        if opts.cmd == "ready":
            verdict = readiness.evaluate(registry, states=_states(registry, ledger),
                                         services=status.service_states(registry),
                                         runs_24h=ledger.runs_since(24))
            print("\n".join(readiness.render(verdict)))
            return 0 if verdict.ready else 1
        if opts.cmd == "hermes-sync":
            counts = hermes_cron.sync(registry, ledger)
            print(", ".join(f"{k} {v}" for k, v in counts.items()))
            return 0
        if opts.cmd == "launchd":
            return _launchd(registry, opts.action, opts.jobs, opts.wait, opts.interrupt)
        return _run(registry, ledger, opts.job, opts.dry_run)
    except (RegistryError, LedgerError) as exc:
        print(f"omni: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
