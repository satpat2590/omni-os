"""The runner's contract: every run or refusal is recorded, budgets hold, the ledger never stops a feed."""
import io
import json
import sys
import textwrap

import pytest

from omni_core import runner
from omni_core.ledger import LedgerError
from omni_core.registry import load


class FakeLedger:
    def __init__(self, spent=0.0, unknown=0, down=False):
        self.spent, self.unknown, self.down = spent, unknown, down
        self.started, self.finished, self.refused = [], [], []

    def _check(self):
        if self.down:
            raise LedgerError("connection refused")

    def month_spend(self, job):
        self._check()
        return self.spent

    def month_unknown(self, job):
        self._check()
        return self.unknown

    def start(self, **kw):
        self._check()
        self.started.append(kw)
        return 7

    def finish(self, run_id, **kw):
        self._check()
        self.finished.append((run_id, kw))

    def refuse(self, **kw):
        self._check()
        self.refused.append(kw)
        return 8


@pytest.fixture
def setup(tmp_path):
    """A registry whose agent harness is a stub that prints its last argument (the prompt)."""
    stub = tmp_path / "stub-harness"
    stub.write_text(f"#!{sys.executable}\nimport sys\nprint(sys.argv[-1])\n")
    stub.chmod(0o755)
    rules = tmp_path / "GLOBAL.md"
    rules.write_text("RULE ONE")
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(textwrap.dedent(f"""
        version: 1
        harnesses:
          script: {{kind: script}}
          opencode: {{kind: opencode, bin: {stub}}}
          pi: {{kind: pi, bin: not-installed-anywhere-xyz}}
        domains:
          omni: {{workdir: {tmp_path}}}
          gone: {{workdir: {tmp_path}/missing}}
        jobs:
          ok: {{domain: omni, harness: script, command: [/bin/echo, hello]}}
          fails: {{domain: omni, harness: script, command: [/bin/sh, -c, "echo boom >&2; exit 3"]}}
          slow: {{domain: omni, harness: script, command: [/bin/sleep, "5"], timeout_s: 1}}
          disabled: {{domain: omni, harness: script, command: [/bin/echo], enabled: false}}
          nodir: {{domain: gone, harness: script, command: [/bin/echo]}}
          agent: {{domain: omni, harness: opencode, prompt: "do the thing", monthly_usd: 1.0}}
          bare: {{domain: omni, harness: opencode, prompt: "do the thing", rules: false}}
          pijob: {{domain: omni, harness: pi, prompt: "x"}}
    """))

    def go(job, ledger):
        out = io.StringIO()
        result = runner.run(load(registry_path), job, ledger, state_dir=tmp_path / "state",
                            rules_path=rules, out=out)
        return result, out.getvalue()

    return go, tmp_path


def test_ok_run_is_started_finished_and_logged(setup):
    go, tmp_path = setup
    ledger = FakeLedger()
    result, out = go("ok", ledger)
    assert (result.status, result.exit_code, result.run_id, out) == ("ok", 0, 7, "hello\n")
    assert ledger.started[0]["job"] == "ok" and ledger.started[0]["harness"] == "script"
    run_id, record = ledger.finished[0]
    assert run_id == 7 and record["status"] == "ok" and record["cost_usd"] == 0.0
    assert "hello" in result.log_path.read_text()


def test_failure_keeps_the_exit_code_and_stderr(setup):
    go, _ = setup
    ledger = FakeLedger()
    result, _ = go("fails", ledger)
    assert (result.status, result.exit_code) == ("failed", 3)
    assert ledger.finished[0][1]["reason"] == "exit code 3"
    assert "boom" in result.log_path.read_text()


def test_timeout_is_recorded_as_timeout(setup):
    go, _ = setup
    ledger = FakeLedger()
    result, _ = go("slow", ledger)
    assert (result.status, result.exit_code) == ("timeout", runner.EXIT_TIMEOUT)
    assert ledger.finished[0][1]["status"] == "timeout"


@pytest.mark.parametrize("job, ledger, fragment", [
    ("disabled", FakeLedger(), "disabled"),
    ("pijob", FakeLedger(), "not installed"),
    ("nodir", FakeLedger(), "does not exist"),
    ("agent", FakeLedger(spent=1.0), "monthly budget reached"),
    ("agent", FakeLedger(unknown=2), "unknown cost"),
])
def test_refusals_start_nothing_and_leave_a_row(setup, job, ledger, fragment):
    go, _ = setup
    result, out = go(job, ledger)
    assert (result.status, result.exit_code, out) == ("refused", runner.EXIT_REFUSED, "")
    assert fragment in result.reason and fragment in ledger.refused[0]["reason"]
    assert not ledger.started


def test_agent_under_budget_runs_with_global_rules_in_front(setup):
    go, _ = setup
    result, out = go("agent", FakeLedger(spent=0.99))
    assert result.status == "ok"
    assert out.startswith("RULE ONE\n\n---\n\ndo the thing")


def test_rules_false_sends_the_bare_prompt(setup):
    go, _ = setup
    _, out = go("bare", FakeLedger())
    assert out == "do the thing\n"


def test_ledger_down_refuses_an_agent_job(setup):
    go, _ = setup
    result, out = go("agent", FakeLedger(down=True))
    assert (result.status, result.exit_code, out) == ("refused", runner.EXIT_NO_LEDGER, "")
    assert "ledger unavailable" in result.reason


def test_ledger_down_still_runs_a_script_job_and_records_it_locally(setup):
    go, tmp_path = setup
    result, out = go("ok", FakeLedger(down=True))
    assert (result.status, out) == ("ok", "hello\n")
    record = json.loads((tmp_path / "state" / "ledger_fallback.jsonl").read_text().splitlines()[-1])
    assert record["job"] == "ok" and record["status"] == "ok" and record["cost_usd"] == 0.0


# --- execute: how a production job is run ---------------------------------------------------

def _ex(tmp_path, script, **kw):
    out, err = io.StringIO(), io.StringIO()
    log_path = tmp_path / "run.log"
    with open(log_path, "wb") as log:
        ex = runner.execute(["/bin/sh", "-c", script], cwd=tmp_path, log=log, out=out, err=err,
                            **{"timeout_s": 10, **kw})
    return ex, out.getvalue(), err.getvalue(), log_path.read_text()


def test_output_is_streamed_to_out_err_and_the_log(tmp_path):
    ex, out, err, log = _ex(tmp_path, "echo one; echo two >&2; echo three", keep_stdout=True)
    assert (ex.status, out, err, ex.stdout) == ("ok", "one\nthree\n", "two\n", "one\nthree\n")
    assert "one" in log and "! two" in log


def test_script_stdout_is_not_kept_in_memory(tmp_path):
    ex, out, _, _ = _ex(tmp_path, "echo hi")
    assert out == "hi\n" and ex.stdout == ""


def test_lines_reach_out_while_the_job_is_still_running(tmp_path):
    import threading, time
    out = io.StringIO()
    with open(tmp_path / "run.log", "wb") as log:
        t = threading.Thread(target=runner.execute, args=(["/bin/sh", "-c", "echo early; sleep 2"],),
                             kwargs=dict(cwd=tmp_path, timeout_s=10, log=log, out=out, err=io.StringIO()))
        t.start()
        time.sleep(1)
        seen_mid_run = out.getvalue()
        t.join()
    assert seen_mid_run == "early\n"


def test_timeout_sends_sigterm_to_the_whole_group_and_lets_it_finish(tmp_path):
    # The child of the shell traps TERM and writes a marker: it got the chance to clean up.
    script = ("sh -c 'trap \"echo cleaned > marker; exit 0\" TERM; while :; do sleep 0.1; done' & wait")
    ex, _, _, _ = _ex(tmp_path, script, timeout_s=1, grace_s=5)
    assert (ex.status, ex.exit_code) == ("timeout", runner.EXIT_TIMEOUT)
    assert (tmp_path / "marker").read_text().strip() == "cleaned"


def test_a_job_that_ignores_sigterm_is_killed_after_the_grace(tmp_path):
    import time
    started = time.time()
    ex, _, _, _ = _ex(tmp_path, "trap '' TERM; sleep 30", timeout_s=1, grace_s=1)
    assert ex.status == "timeout" and time.time() - started < 10


def test_a_missing_program_is_a_failure_not_a_crash(tmp_path):
    with open(tmp_path / "run.log", "wb") as log:
        ex = runner.execute(["/no/such/program"], cwd=tmp_path, timeout_s=5, log=log,
                            out=io.StringIO(), err=io.StringIO())
    assert (ex.status, ex.exit_code) == ("failed", 127)


def test_job_workdir_overrides_the_domain_workdir(setup, tmp_path):
    go, base = setup
    reg_path = base / "registry.yaml"
    other = base / "elsewhere"
    other.mkdir()
    reg_path.write_text(reg_path.read_text() + f"  pwd: {{domain: omni, harness: script, command: [/bin/pwd], workdir: {other}}}\n")
    result, out = go("pwd", FakeLedger())
    assert result.status == "ok" and out.strip().endswith("elsewhere")


def test_old_run_logs_are_pruned(tmp_path):
    import os, time
    old, new = tmp_path / "old.log", tmp_path / "new.log"
    old.write_text("x"), new.write_text("x")
    os.utime(old, (time.time() - 30 * 86400,) * 2)
    runner._prune_run_logs(tmp_path, keep_days=14)
    assert not old.exists() and new.exists()


def test_sigterm_to_the_runner_reaches_the_job(tmp_path):
    """launchd stops a job by sending SIGTERM to the process it started: the runner."""
    import signal, subprocess, time
    code = textwrap.dedent(f"""
        import io, sys
        from omni_core import runner
        with open({str(tmp_path / 'run.log')!r}, 'wb') as log:
            ex = runner.execute(['/bin/sh', '-c', "trap 'echo got-term > marker; exit 0' TERM; echo up; while :; do sleep 0.1; done"],
                                cwd={str(tmp_path)!r}, timeout_s=60, log=log, grace_s=5)
        print('RESULT', ex.status, ex.reason, file=sys.stderr)
    """)
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout.readline() == "up\n"
    proc.send_signal(signal.SIGTERM)
    _, err = proc.communicate(timeout=20)
    assert (tmp_path / "marker").read_text().strip() == "got-term"
    assert "RESULT failed stopped by SIGTERM" in err


def test_a_script_can_report_its_cost_through_the_usage_file(tmp_path):
    from omni_core import adapters
    from omni_core.registry import Harness, Job
    job = Job(name="j", domain="omni", harness="script", command=["true"])
    inv = adapters.build(Harness(name="script", kind="script"), job, None, tmp_path)
    assert inv.env["OMNI_USAGE_FILE"] == str(tmp_path / "script-usage.json")
    assert adapters.usage(Harness(name="script", kind="script"), inv, "").cost_source == "none"
    (tmp_path / "script-usage.json").write_text('{"cost_usd": 0.0123, "model": "decision-panel"}')
    used = adapters.usage(Harness(name="script", kind="script"), inv, "")
    assert (used.cost_usd, used.cost_source, used.model) == (0.0123, "script_usage_file", "decision-panel")
