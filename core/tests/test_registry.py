"""The registry rejects anything it does not understand, and the shipped file is valid."""
import textwrap

import pytest


from omni_core.registry import DEFAULT_PATH, RegistryError, load

BASE = """
version: 1
harnesses:
  script: {kind: script}
  hermes: {kind: hermes, bin: /bin/echo}
domains:
  omni: {workdir: /tmp}
jobs:
"""


def _write(tmp_path, jobs: str):
    path = tmp_path / "registry.yaml"
    path.write_text(BASE + textwrap.indent(textwrap.dedent(jobs), "  "))
    return path




def test_script_and_agent_jobs_load(tmp_path):
    registry = load(_write(tmp_path, """
        a: {domain: omni, harness: script, command: [/bin/echo, hi]}
        b: {domain: omni, harness: hermes, prompt: "say ok", monthly_usd: 1}
    """))
    assert registry.jobs["a"].command == ("/bin/echo", "hi")
    assert registry.jobs["b"].monthly_usd == 1.0
    assert registry.jobs["b"].enabled and registry.jobs["b"].rules


def test_prompt_file_is_read_relative_to_the_registry(tmp_path):
    (tmp_path / "p.md").write_text("from a file")
    registry = load(_write(tmp_path, "b: {domain: omni, harness: hermes, prompt_file: p.md}"))
    assert registry.jobs["b"].prompt == "from a file"


@pytest.mark.parametrize("jobs, message", [
    ("a: {domain: omni, harness: script, command: [/bin/echo], monthly_usdd: 1}", "unknown key"),
    ("a: {domain: nope, harness: script, command: [/bin/echo]}", "unknown domain"),
    ("a: {domain: omni, harness: nope, command: [/bin/echo]}", "unknown harness"),
    ("a: {domain: omni, harness: script}", "needs `command`"),
    ("a: {domain: omni, harness: script, command: [/bin/echo], prompt: x}", "no prompt or model"),
    ("a: {domain: omni, harness: hermes}", "needs `prompt`"),
    ("a: {domain: omni, harness: hermes, prompt: x, command: [ls]}", "only for script jobs"),
    ("a: {domain: omni, harness: hermes, prompt: x, timeout_s: 0}", "timeout_s"),
    ("a: {domain: omni, harness: hermes, prompt: x, monthly_usd: -1}", "monthly_usd"),
    ("a: {domain: omni, harness: hermes, prompt: x, enabled: 'yes'}", "true or false"),
])
def test_invalid_jobs_are_rejected(tmp_path, jobs, message):
    with pytest.raises(RegistryError, match=message):
        load(_write(tmp_path, jobs))


def test_a_job_named_like_a_yaml_boolean_is_rejected_not_lost(tmp_path):
    with pytest.raises(RegistryError, match="not a string; quote it"):
        load(_write(tmp_path, "off: {domain: omni, harness: script, command: [/bin/echo]}"))


def test_unknown_job_names_the_known_ones(tmp_path):
    registry = load(_write(tmp_path, "a: {domain: omni, harness: script, command: [/bin/echo]}"))
    with pytest.raises(RegistryError, match="known: a"):
        registry.job("b")


def test_missing_file_and_bad_version(tmp_path):
    with pytest.raises(RegistryError, match="cannot read"):
        load(tmp_path / "absent.yaml")
    path = tmp_path / "r.yaml"
    path.write_text("version: 2\n")
    with pytest.raises(RegistryError, match="version must be 1"):
        load(path)


def test_the_default_is_this_machines_registry_else_the_base_example(tmp_path, monkeypatch):
    from omni_core import registry
    real = tmp_path / "registry.yaml"
    monkeypatch.setattr(registry, "REAL_PATH", real)
    assert registry.default_path() == registry.EXAMPLE_PATH          # fresh Omni OS checkout
    real.write_text("version: 1\n")
    assert registry.default_path() == real                           # an instance's own registry wins


def test_the_shipped_base_example_is_a_valid_atma_only_registry():
    from omni_core import registry
    reg = registry.load(registry.EXAMPLE_PATH)
    assert set(reg.domains) == {"omni", "atma"}
    assert {"atma-auto-verify", "omni-mindmap-etl"} <= set(reg.jobs)
    assert all(job.domain in ("omni", "atma") for job in reg.jobs.values())
