"""Plans, job status and the generated diagrams: structure from the registry, colour from facts."""
import textwrap

import pytest


from omni_core import diagram, jobstate, status
from omni_core.jobstate import LaunchdFacts
from omni_core.registry import DEFAULT_PATH, RegistryError, load

REGISTRY = """
version: 1
harnesses:
  script: {kind: script}
domains:
  d: {workdir: /tmp}
services:
  db: {domain: d, launchd: dev.omni.db, port: 5433}
jobs:
  collect: {domain: d, harness: script, command: [/bin/echo], enabled: false, launchd: dev.omni.collect, schedule: "every 15m"}
  ingest: {domain: d, harness: script, command: [/bin/echo], enabled: false, launchd: dev.omni.ingest}
  sync: {domain: d, harness: script, command: [/bin/echo], enabled: false, launchd: dev.omni.sync, log: /logs/sync_*.log}
  viaomni: {domain: d, harness: script, command: [/bin/echo]}
  timed: {domain: d, harness: script, command: [/bin/echo], launchd: dev.omni.timed, timeout_s: 600, schedule: "every 15m"}
  parked: {domain: d, harness: script, command: [/bin/echo], enabled: false}
plans:
  news:
    description: test plan
    stages:
      - {name: Collect, jobs: [collect]}
      - {name: Ingest, jobs: [ingest], needs: [Collect]}
      - {name: Copy, jobs: [sync], needs: [Ingest]}
"""
NOW = 1_000_000.0


def _load(tmp_path, text=REGISTRY):
    path = tmp_path / "registry.yaml"
    path.write_text(textwrap.dedent(text))
    return load(path)


def _states(registry, facts, mtimes, intervals=None, last_runs=None):
    intervals = intervals or {}
    return jobstate.job_states(
        registry, last_runs=last_runs, now=NOW,
        facts_of=lambda label: facts.get(label, LaunchdFacts(True, 0, 3)),
        plist_of=lambda label: (intervals.get(label, 900), f"/logs/{label}.log"),
        mtime_of=lambda path: mtimes.get(str(path)))


@pytest.mark.parametrize("stages, message", [
    ("[{name: A, jobs: [nope]}]", "unknown job"),
    ("[{name: A, jobs: [collect]}, {name: A, jobs: [ingest]}]", "duplicate stage"),
    ("[{name: A, jobs: [collect], needs: [B]}, {name: B, jobs: [ingest]}]", "not an earlier stage"),
    ("[{name: A, jobs: []}]", "non-empty list"),
    ("[{jobs: [collect]}]", "`name` is required"),
    ("[]", "non-empty list"),
])
def test_invalid_plans_are_rejected(tmp_path, stages, message):
    text = REGISTRY.split("plans:")[0] + f"plans:\n  p:\n    stages: {stages}\n"
    with pytest.raises(RegistryError, match=message):
        _load(tmp_path, text)


def test_launchd_jobs_are_judged_from_exit_code_and_log_age(tmp_path):
    registry = _load(tmp_path)
    states = _states(
        registry,
        facts={"dev.omni.ingest": LaunchdFacts(True, 1, 4), "dev.omni.sync": LaunchdFacts(True, None, 0)},
        mtimes={"/logs/dev.omni.collect.log": NOW - 60, "/logs/dev.omni.ingest.log": NOW - 60,
                "/logs/sync_*.log": NOW - 600})
    assert states["collect"].status == "ok" and "60s ago" in states["collect"].detail
    assert states["ingest"].status == "failed" and "exit code 1" in states["ingest"].detail
    assert states["sync"].status == "waiting"          # not run since boot, and its own log is recent
    assert states["sync"].last_activity == NOW - 600   # the registry's `log` override is what was read


def test_overdue_unloaded_and_unknown(tmp_path):
    registry = _load(tmp_path)
    states = _states(
        registry,
        facts={"dev.omni.ingest": LaunchdFacts(False, None, None)},
        mtimes={"/logs/dev.omni.collect.log": NOW - 1801},      # more than 2 x 900s
        intervals={"dev.omni.sync": None})
    assert states["collect"].status == "overdue"
    assert states["ingest"].status == "failed" and "not loaded" in states["ingest"].detail
    assert states["sync"].status == "unknown"                   # ran, exit 0, but no log anywhere
    assert states["parked"].status == "unknown" and states["parked"].fired_by == "nobody"


def test_jobs_run_through_omni_are_judged_from_the_ledger(tmp_path):
    registry = _load(tmp_path)
    assert _states(registry, {}, {})["viaomni"].status == "unknown"
    ok = _states(registry, {}, {}, last_runs={"viaomni": ("ok", None, NOW - 30)})["viaomni"]
    assert (ok.status, ok.fired_by) == ("ok", "omni")
    bad = _states(registry, {}, {}, last_runs={"viaomni": ("timeout", "timed out after 5s", NOW - 30)})["viaomni"]
    assert bad.status == "failed" and "timed out after 5s" in bad.detail


def test_a_running_launchd_job_is_ok_even_when_its_log_is_quiet(tmp_path):
    registry = _load(tmp_path)
    states = _states(registry, facts={"dev.omni.collect": LaunchdFacts(True, 0, 9, running=True)},
                     mtimes={"/logs/dev.omni.collect.log": NOW - 5000})
    assert states["collect"].status == "ok" and "running now" in states["collect"].detail


def test_jobs_launchd_fires_through_omni_combine_timer_and_ledger(tmp_path):
    registry = _load(tmp_path)
    timed = lambda **kw: _states(registry, **{"facts": {}, "mtimes": {}, **kw})["timed"]
    assert timed().status == "waiting"
    assert timed(last_runs={"timed": ("ok", None, NOW - 60)}).status == "ok"
    assert timed(last_runs={"timed": ("ok", None, NOW - 1801)}).status == "overdue"
    failed = timed(last_runs={"timed": ("failed", "exit code 2", NOW - 60)})
    assert failed.status == "failed" and "exit code 2" in failed.detail and failed.fired_by == "omni"
    assert timed(facts={"dev.omni.timed": LaunchdFacts(False, None, None)}).status == "failed"
    running = timed(facts={"dev.omni.timed": LaunchdFacts(True, 0, 3, running=True)},
                    last_runs={"timed": ("running", None, NOW - 60)})
    assert running.status == "ok" and "running now" in running.detail
    stuck = timed(last_runs={"timed": ("running", None, NOW - 3 * 3600)})
    assert stuck.status == "failed" and "still says running" in stuck.detail


def test_worst_status_wins():
    assert jobstate.worst(["ok", "waiting", "overdue"]) == "overdue"
    assert jobstate.worst(["ok", "failed", "overdue"]) == "failed"
    assert jobstate.worst(["ok", "ok"]) == "ok"


def test_plan_diagram_has_a_box_per_job_an_arrow_per_need_and_status_classes(tmp_path):
    registry = _load(tmp_path)
    states = _states(registry, {"dev.omni.ingest": LaunchdFacts(True, 1, 4)},
                     {"/logs/dev.omni.collect.log": NOW - 60, "/logs/dev.omni.ingest.log": NOW - 60,
                      "/logs/sync_*.log": NOW - 60})
    text = diagram.plan_mermaid(registry, registry.plans["news"], states, now=NOW)
    assert text.startswith("flowchart TD")
    assert 'j_collect["collect<br/>ok, 60s ago"]:::ok' in text
    assert 'j_ingest["ingest<br/>failed, 60s ago"]:::failed' in text
    assert "s0 --> s1" in text and "s1 --> s2" in text and "s0 --> s2" not in text
    assert "classDef failed" in text


def test_static_diagram_carries_no_status_so_it_only_changes_with_the_registry(tmp_path):
    registry = _load(tmp_path)
    text = diagram.plan_mermaid(registry, registry.plans["news"])
    assert 'j_collect["collect<br/>every 15m"]' in text
    assert ":::" not in text and "classDef" not in text
    doc = diagram.markdown(registry)
    assert doc.count("```mermaid") == 2 and "## Plan: news" in doc


def test_snapshot_rolls_status_up_and_lists_jobs_outside_any_plan(tmp_path):
    registry = _load(tmp_path)
    states = _states(registry, {"dev.omni.ingest": LaunchdFacts(True, 1, 4)},
                     {"/logs/dev.omni.collect.log": NOW - 60, "/logs/dev.omni.ingest.log": NOW - 60,
                      "/logs/sync_*.log": NOW - 60})
    services = status.service_states(registry, state_of=lambda label: "running", is_open=lambda port: True)
    data = diagram.snapshot(registry, states, services, now=NOW)
    plan = data["plans"][0]
    assert (plan["name"], plan["status"]) == ("news", "failed")
    assert [s["status"] for s in plan["stages"]] == ["ok", "failed", "ok"]
    assert [j["name"] for g in data["other_jobs"] for j in g["jobs"]] == ["parked", "timed", "viaomni"]
    assert data["services"][0]["ok"] and data["counts"]["failed"] == 1
