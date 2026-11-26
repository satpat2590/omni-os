"""Schedules: one registry line becomes launchd keys, and long intervals must be clock times."""
import pytest

from omni_core import launchd, schedule
from omni_core.registry import load
from omni_core.schedule import ScheduleError


@pytest.mark.parametrize("text, keys", [
    ("every 15m", {"StartInterval": 900}),
    ("every 2h", {"StartInterval": 7200}),
    ("17:30", {"StartCalendarInterval": [{"Hour": 17, "Minute": 30}]}),
    ("sat 17:30", {"StartCalendarInterval": [{"Hour": 17, "Minute": 30, "Weekday": 6}]}),
    (["05:00", "mon-fri 16:45"], {"StartCalendarInterval": [{"Hour": 5, "Minute": 0}] + [
        {"Hour": 16, "Minute": 45, "Weekday": d} for d in range(1, 6)]}),
    ("sun,wed 09:05", {"StartCalendarInterval": [{"Hour": 9, "Minute": 5, "Weekday": 0},
                                                 {"Hour": 9, "Minute": 5, "Weekday": 3}]}),
    ("*:10", {"StartCalendarInterval": [{"Minute": 10}]}),
    ("mon-fri *:00", {"StartCalendarInterval": [{"Minute": 0, "Weekday": d} for d in range(1, 6)]}),
])
def test_schedules_become_launchd_keys(text, keys):
    assert schedule.to_launchd(text) == keys


@pytest.mark.parametrize("text, fragment", [
    ("every 4h", "clock times"), ("every 30s", "under a minute"), ("25:00", "no such time"), ("*:75", "no such time"),
    ("fri-mon 10:00", "backwards"), ("noon", "cannot read"), (["every 15m", "10:00"], "stands alone"),
    (["10:00", "10:00"], "twice"), ([], "non-empty"),
])
def test_bad_schedules_are_refused(text, fragment):
    with pytest.raises(ScheduleError, match=fragment):
        schedule.to_launchd(text)


@pytest.mark.parametrize("text, gap", [
    ("every 15m", 900), ("17:30", 86400), ("sat 17:30", 7 * 86400), (["05:30", "17:30"], 43200),
    (["05:00", "mon-fri 16:45"], 86400),          # the weekend: Sat 05:00 -> Sun 05:00
    ("mon-fri 16:45", 3 * 86400),                 # Fri 16:45 -> Mon 16:45
    ("*:10", 3600),                               # every hour at ten past
])
def test_interval_is_the_longest_normal_gap(text, gap):
    assert schedule.interval_s(text) == gap


def test_a_rendered_plist_keeps_env_and_logs_and_wraps_the_command(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text(f"""
version: 1
harnesses: {{script: {{kind: script}}}}
domains: {{d: {{workdir: {tmp_path}}}}}
jobs:
  feed: {{domain: d, harness: script, command: [/bin/bash, "~/x.sh"], launchd: dev.omni.feed, schedule: ["05:30", "17:30"]}}
""")
    registry = load(reg)
    job = registry.job("feed")
    existing = {"Label": "dev.omni.feed", "StartInterval": 43200, "RunAtLoad": True,
                "EnvironmentVariables": {"PATH": "/custom"}, "StandardOutPath": "/logs/feed.log",
                "ProgramArguments": ["/old"]}
    plist = launchd.render(registry, job, existing)
    assert plist["ProgramArguments"][1:] == [str(launchd.OMNI_JOB), "feed", "--", "/bin/bash",
                                             str(launchd.HOME / "x.sh")]
    assert plist["EnvironmentVariables"] == {"PATH": "/custom"} and plist["StandardOutPath"] == "/logs/feed.log"
    assert "StartInterval" not in plist and "RunAtLoad" not in plist
    assert plist["StartCalendarInterval"] == [{"Hour": 5, "Minute": 30}, {"Hour": 17, "Minute": 30}]
    assert plist["WorkingDirectory"] == str(tmp_path)
    fresh = launchd.render(registry, job, None)
    assert fresh["UserName"] == launchd.HOME.name and fresh["StandardOutPath"].endswith("state/logs/feed.log")
    assert launchd.diff(existing, plist) and launchd.diff(plist, plist) == []
