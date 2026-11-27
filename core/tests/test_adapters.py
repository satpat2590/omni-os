"""Adapters build the headless command for each harness and read cost back without guessing."""
import json
import os

from omni_core import adapters
from omni_core.registry import Harness, Job

HERMES = Harness("hermes", "hermes", "/bin/echo")
OPENCODE = Harness("opencode", "opencode", "/bin/echo")
PI = Harness("pi", "pi", "/bin/echo")
SCRIPT = Harness("script", "script")


def _job(harness, **kw):
    return Job(name="j", domain="omni", harness=harness, **kw)


def test_script_runs_its_command_at_zero_known_cost(tmp_path):
    inv = adapters.build(SCRIPT, _job("script", command=("/bin/echo", "hi")), None, tmp_path)
    assert inv.argv == ["/bin/echo", "hi"]
    used = adapters.usage(SCRIPT, inv, "")
    assert (used.cost_usd, used.cost_source) == (0.0, "none")


def test_script_arguments_starting_with_tilde_are_expanded(tmp_path):
    job = _job("script", command=("/bin/bash", "~/edoras/scripts/run.sh", "-c", "cd ~/edoras && x"))
    inv = adapters.build(SCRIPT, job, None, tmp_path)
    home = os.path.expanduser("~")
    assert inv.argv == ["/bin/bash", f"{home}/edoras/scripts/run.sh", "-c", "cd ~/edoras && x"]


def test_hermes_oneshot_with_profile_model_and_usage_file(tmp_path):
    inv = adapters.build(HERMES, _job("hermes", prompt="p", profile="argus", model="m"), "p", tmp_path)
    assert inv.argv == ["/bin/echo", "-p", "argus", "-z", "p", "--usage-file",
                        str(tmp_path / "hermes-usage.json"), "-m", "m"]


def test_hermes_cost_comes_from_the_usage_file_including_auxiliary(tmp_path):
    inv = adapters.build(HERMES, _job("hermes", prompt="p"), "p", tmp_path)
    inv.usage_file.write_text(json.dumps({
        "estimated_cost_usd": 0.02, "input_tokens": 23579, "output_tokens": 23,
        "model": "deepseek/deepseek-v4-pro", "auxiliary": {"estimated_cost_usd": 0.001}}))
    used = adapters.usage(HERMES, inv, "ok")
    assert round(used.cost_usd, 6) == 0.021
    assert (used.tokens_in, used.tokens_out, used.cost_source) == (23579, 23, "hermes_usage_file")
    assert used.model == "deepseek/deepseek-v4-pro"


def test_hermes_cost_is_unknown_without_a_usage_file(tmp_path):
    inv = adapters.build(HERMES, _job("hermes", prompt="p"), "p", tmp_path)
    used = adapters.usage(HERMES, inv, "ok")
    assert (used.cost_usd, used.cost_source) == (None, "unknown")


def test_opencode_command_and_summed_step_costs(tmp_path):
    inv = adapters.build(OPENCODE, _job("opencode", prompt="p", model="x/y", agent="build"), "p", tmp_path)
    assert inv.argv == ["/bin/echo", "run", "--format", "json", "-m", "x/y", "--agent", "build", "p"]
    step = lambda cost, i, o: json.dumps({"type": "step_finish", "part": {
        "cost": cost, "tokens": {"input": i, "output": o}}})
    stdout = "\n".join([json.dumps({"type": "text", "part": {"text": "ok"}}), "not json",
                        step(0.0003, 7655, 3), step(0.0002, 100, 5)])
    used = adapters.usage(OPENCODE, inv, stdout)
    assert round(used.cost_usd, 6) == 0.0005
    assert (used.tokens_in, used.tokens_out, used.cost_source) == (7755, 8, "opencode_events")


def test_opencode_cost_is_unknown_when_a_step_has_no_cost_or_no_steps_ran(tmp_path):
    inv = adapters.build(OPENCODE, _job("opencode", prompt="p"), "p", tmp_path)
    assert adapters.usage(OPENCODE, inv, "").cost_usd is None
    partial = "\n".join([json.dumps({"type": "step_finish", "part": {"cost": 0.1, "tokens": {}}}),
                         json.dumps({"type": "step_finish", "part": {"tokens": {}}})])
    assert adapters.usage(OPENCODE, inv, partial).cost_usd is None


def _pi_event(kind, role, total, i=0, o=0):
    cost = {} if total is None else {"total": total}
    return json.dumps({"type": kind, "message": {"role": role, "model": "deepseek/deepseek-v4-flash",
                                                  "usage": {"input": i, "output": o, "cost": cost}}})


def test_pi_command_and_cost_from_assistant_message_ends(tmp_path):
    inv = adapters.build(PI, _job("pi", prompt="p", model="m", tools=("read", "ls")), "p", tmp_path)
    assert inv.argv == ["/bin/echo", "-p", "--mode", "json", "--no-session", "--approve", "--provider",
                        "openrouter", "--model", "m", "--tools", "read,ls", "p"]
    stdout = "\n".join([
        _pi_event("message_end", "user", 9.0),                  # not the model's spend
        _pi_event("message_start", "assistant", 0.0),           # placeholder before the call
        _pi_event("message_end", "assistant", 0.0002, 1762, 16),
        _pi_event("turn_end", "assistant", 0.0002, 1762, 16),   # repeats the message above
        _pi_event("message_end", "assistant", 0.0001, 100, 4),
    ])
    used = adapters.usage(PI, inv, stdout)
    assert round(used.cost_usd, 6) == 0.0003
    assert (used.tokens_in, used.tokens_out, used.cost_source) == (1862, 20, "pi_events")
    assert used.model == "deepseek/deepseek-v4-flash"


def test_pi_cost_is_unknown_without_a_costed_assistant_message(tmp_path):
    inv = adapters.build(PI, _job("pi", prompt="p"), "p", tmp_path)
    assert adapters.usage(PI, inv, '{"cost": 1}').cost_usd is None
    assert adapters.usage(PI, inv, _pi_event("message_end", "assistant", None)).cost_usd is None


def test_missing_binary_is_reported():
    assert adapters.unavailable(SCRIPT) is None
    assert adapters.unavailable(HERMES) is None
    assert "not installed" in adapters.unavailable(Harness("pi", "pi", "definitely-not-a-binary-xyz"))
    assert "not installed" in adapters.unavailable(Harness("h", "hermes", "/no/such/bin"))
