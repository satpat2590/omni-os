"""Services in the registry, and the status view that says which are down and who fires each job."""
import textwrap

import pytest


from omni_core import status
from omni_core.registry import DEFAULT_PATH, RegistryError, load

REGISTRY = """
version: 1
harnesses:
  script: {kind: script}
domains:
  omni: {workdir: /tmp}
  edoras: {workdir: /tmp}
services:
  postgres: {domain: omni, launchd: dev.omni.postgres, port: 5433}
  api: {domain: edoras, launchd: dev.omni.edoras-api, port: 8420}
  realtime: {domain: edoras, launchd: dev.omni.edoras-realtime}
jobs:
  via-omni: {domain: omni, harness: script, command: [/bin/echo]}
  via-launchd: {domain: edoras, harness: script, command: [/bin/echo], enabled: false, launchd: dev.omni.x}
  parked: {domain: edoras, harness: script, command: [/bin/echo], enabled: false}
"""


def _load(tmp_path, text=REGISTRY):
    path = tmp_path / "registry.yaml"
    path.write_text(textwrap.dedent(text))
    return load(path)


def test_all_up_is_exit_zero_and_jobs_are_grouped_by_who_fires_them(tmp_path):
    registry = _load(tmp_path)
    states = status.service_states(registry, state_of=lambda label: "running", is_open=lambda port: True)
    lines, code = status.render(registry, states)
    text = "\n".join(lines)
    assert code == 0 and "DOWN" not in text
    assert "edoras    0 through omni run, 1 fired by launchd directly, 1 disabled" in text
    assert "omni      1 through omni run, 0 fired by launchd directly, 0 disabled" in text


def test_a_stopped_service_and_a_closed_port_are_both_down(tmp_path):
    registry = _load(tmp_path)
    state_of = lambda label: "not running" if label.endswith("realtime") else "running"
    states = status.service_states(registry, state_of=state_of, is_open=lambda port: port != 8420)
    lines, code = status.render(registry, states)
    assert code == 1
    assert lines[-1] == "DOWN: api, realtime"
    by_name = {s.name: s for s in states}
    assert by_name["postgres"].ok and by_name["api"].port_open is False
    assert by_name["realtime"].port_open is None      # no port declared, and not probed when stopped


@pytest.mark.parametrize("entry, message", [
    ("{domain: nope, launchd: x}", "unknown domain"),
    ("{domain: omni}", "`launchd`"),
    ("{domain: omni, launchd: x, port: 70000}", "port must be"),
    ("{domain: omni, launchd: x, prot: 1}", "unknown key"),
])
def test_invalid_services_are_rejected(tmp_path, entry, message):
    text = REGISTRY.replace("  realtime: {domain: edoras, launchd: dev.omni.edoras-realtime}",
                            f"  realtime: {entry}")
    with pytest.raises(RegistryError, match=message):
        _load(tmp_path, text)
