"""Hermes cron jobs are watched and recorded, never fired; readiness needs every check to pass."""
import json
import sqlite3
import textwrap

import pytest

from omni_core import hermes_cron, readiness
from omni_core.jobstate import JobState
from omni_core.registry import RegistryError, load
from omni_core.status import ServiceState

NOW = 2_000_000_000.0


def _hermes_home(tmp_path, jobs, sessions=()):
    home = tmp_path / "hermes"
    (home / "cron").mkdir(parents=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": jobs}))
    db = sqlite3.connect(home / "state.db")
    db.execute("create table sessions (id text, source text, title text, model text, started_at real, "
               "ended_at real, end_reason text, input_tokens int, output_tokens int, "
               "actual_cost_usd real, estimated_cost_usd real)")
    db.executemany("insert into sessions values (?,?,?,?,?,?,?,?,?,?,?)", sessions)
    db.commit()
    db.close()
    return home


def _registry(tmp_path, extra=""):
    path = tmp_path / "registry.yaml"
    path.write_text(textwrap.dedent(f"""
        version: 1
        harnesses: {{script: {{kind: script}}, hermes: {{kind: hermes, bin: /bin/echo}}}}
        domains: {{edoras: {{workdir: {tmp_path}}}, omni: {{workdir: {tmp_path}}}}}
        jobs:
          brief: {{domain: edoras, harness: hermes, profile: default, hermes_cron: "abc"}}
          feed: {{domain: edoras, harness: script, command: [/bin/echo], launchd: dev.omni.feed, schedule: "every 15m"}}
    """) + extra)
    return load(path)


def test_a_hermes_cron_job_takes_no_prompt_and_is_never_run_by_omni(tmp_path):
    from omni_core import runner
    registry = _registry(tmp_path)
    assert runner._refusal(registry, registry.job("brief"), ledger=None).startswith("fired by Hermes cron")
    with pytest.raises(RegistryError, match="hermes harness"):
        _registry(tmp_path, '  bad: {domain: edoras, harness: script, hermes_cron: "x"}\n')


@pytest.mark.parametrize("job, status, fragment", [
    ({"id": "abc", "enabled": True, "last_status": "ok", "last_run_at": "2033-05-18T03:00:00+00:00",
      "next_run_at": "2033-05-18T04:00:00+00:00"}, "ok", "last run"),
    ({"id": "abc", "enabled": True, "last_status": "error", "last_error": "boom\nmore"}, "failed", "boom"),
    ({"id": "abc", "enabled": True, "last_status": "ok", "next_run_at": "2033-05-17T00:00:00+00:00"},
     "overdue", "was due"),
    ({"id": "abc", "enabled": False}, "unknown", "paused"),
    ({"id": "zzz", "enabled": True}, "failed", "not found"),
])
def test_hermes_job_status_comes_from_jobs_json(tmp_path, job, status, fragment):
    home = _hermes_home(tmp_path, [job])
    got, detail = hermes_cron.judge(hermes_cron.facts("default", "abc", home), NOW)
    assert got == status and fragment in detail


class Ledger:
    def __init__(self):
        self.rows = {}

    def record_external(self, **kw):
        new = kw["external_id"] not in self.rows
        self.rows.setdefault(kw["external_id"], kw)
        return new


def test_sync_records_finished_sessions_once_matched_by_title(tmp_path):
    home = _hermes_home(tmp_path, [{"id": "abc", "name": "Argus Brief", "enabled": True}], sessions=[
        ("s1", "cron", "Argus Brief · Nov 18 09:00", "m", NOW - 100, NOW - 50, "cron_complete", 10, 2, None, 0.25),
        ("s2", "cron", "Something Else · Nov 18", "m", NOW - 100, NOW - 50, None, 1, 1, 0.01, None),
        ("s3", "cron", None, "m", NOW - 100, NOW - 50, "cron_complete", 0, 0, None, None),
        ("s4", "cron", "Argus Brief · Nov 18 10:00", "m", NOW - 40, None, None, 0, 0, None, None),
        ("s5", "cron", "Argus Brief · Nov 18 11:00", "m", NOW - 30, NOW - 20, "startup_orphan_reap", 0, 0, None, None),
    ])
    registry, ledger = _registry(tmp_path), Ledger()
    assert hermes_cron.sync(registry, ledger, home=home, now=NOW) == {"recorded": 3, "already": 0, "unmatched": 1}
    s1 = ledger.rows["hermes:default:s1"]
    assert (s1["job"], s1["cost_usd"], s1["status"], s1["fired_by"]) == ("brief", 0.25, "ok", "hermes-cron")
    assert ledger.rows["hermes:default:s2"]["job"] == "hermes:default"     # cost with no job: still counted
    assert ledger.rows["hermes:default:s5"]["status"] == "failed"
    assert "hermes:default:s4" not in ledger.rows and "hermes:default:s3" not in ledger.rows
    assert hermes_cron.sync(registry, ledger, home=home, now=NOW)["recorded"] == 0


READY = """
readiness:
  domains: [edoras]
  min_success: 0.9
  freshness:
    candles: {sqlite: /tmp/x.db, query: "select 1", max_age: 1h}
"""


def _verdict(tmp_path, *, states=None, services=None, runs=None, newest=NOW - 60):
    registry = _registry(tmp_path, READY)
    states = states or {"brief": JobState("brief", "ok", "fine"), "feed": JobState("feed", "ok", "fine")}
    services = services if services is not None else [ServiceState("pg", "omni", "dev.omni.pg", "running", 5433, True)]
    runs = runs if runs is not None else [("feed", "ok", "omni")] * 10
    return readiness.evaluate(registry, states=states, services=services, runs_24h=runs, now=NOW,
                              value_of=lambda probe: newest)


def test_ready_when_everything_holds(tmp_path):
    verdict = _verdict(tmp_path)
    assert verdict.ready and not verdict.failures()


@pytest.mark.parametrize("change, failing", [
    (dict(services=[ServiceState("pg", "omni", "dev.omni.pg", "not running", 5433, False)]), "pg"),
    (dict(states={"brief": JobState("brief", "failed", "x"), "feed": JobState("feed", "ok", "")}), "brief"),
    (dict(runs=[("feed", "ok", "omni")] * 9 + [("feed", "running", "omni"), ("feed", "refused", "omni")]), None),
    (dict(runs=[("feed", "ok", "omni")] * 9 + [("feed", "failed", "omni")] * 2), "success rate"),
    (dict(runs=[]), "feed ran"),
    (dict(newest=NOW - 7200), "candles"),
    (dict(newest=None), "candles"),
])
def test_any_failing_check_means_not_ready(tmp_path, change, failing):
    verdict = _verdict(tmp_path, **change)
    if failing is None:
        assert verdict.ready                 # running and refused rows are not finished runs
    else:
        assert not verdict.ready and failing in [c.name for c in verdict.failures()]


def test_a_probe_that_errors_is_a_failed_check_not_a_crash(tmp_path):
    registry = _registry(tmp_path, READY)
    def boom(probe):
        raise RuntimeError("database is locked")
    verdict = readiness.evaluate(registry, states={"brief": JobState("brief", "ok", ""), "feed": JobState("feed", "ok", "")},
                                 services=[], runs_24h=[("feed", "ok", "omni")], now=NOW, value_of=boom)
    assert not verdict.ready and "database is locked" in verdict.failures()[0].detail
