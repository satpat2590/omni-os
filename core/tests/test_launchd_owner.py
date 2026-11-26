"""/Library/LaunchDaemons is shared by every account: core never rewrites another user's plist."""
import plistlib
import textwrap

import pytest

from omni_core import launchd
from omni_core.registry import load


def _registry(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(textwrap.dedent(f"""
        version: 1
        harnesses: {{script: {{kind: script}}}}
        domains: {{omni: {{workdir: {tmp_path}}}}}
        jobs:
          nightly:
            domain: omni
            harness: script
            launchd: dev.omni.nightly
            schedule: "02:00"
            command: [/bin/echo, hi]
    """))
    return load(path)


def _plist(tmp_path, user):
    with open(tmp_path / "dev.omni.nightly.plist", "wb") as f:
        plistlib.dump({"Label": "dev.omni.nightly", "UserName": user, "ProgramArguments": ["/bin/true"]}, f)


def test_apply_refuses_a_plist_that_runs_as_another_user(tmp_path):
    reg = _registry(tmp_path)
    _plist(tmp_path, "someone-else")
    with pytest.raises(launchd.LaunchdError, match="runs as someone-else"):
        launchd.apply(reg, reg.jobs["nightly"], plist_dir=tmp_path, running=lambda _: False)
    with open(tmp_path / "dev.omni.nightly.plist", "rb") as f:
        assert plistlib.load(f)["ProgramArguments"] == ["/bin/true"]      # untouched


def test_owner_is_none_for_this_user_or_no_plist(tmp_path):
    assert launchd.owner(None) is None
    assert launchd.owner({"UserName": launchd.HOME.name}) is None
    assert launchd.owner({"UserName": "someone-else"}) == "someone-else"


def test_new_plists_use_omni_svc_that_exists_and_no_domain_paths():
    assert launchd.OMNI_SVC.exists()
    assert "edoras" not in launchd.DEFAULT_PATH
