"""When a job fires, written once in the registry and turned into launchd keys.

Two forms, never mixed in one job:

    every 15m | every 2h | every 90s      -> StartInterval: counted from when launchd loaded the
                                             job, so its phase moves on every reboot or reload.
                                             Only for short intervals, where phase does not matter.
    "17:30" | "mon-fri 16:45" | "sat 17:30" | "*:10" | a list of these
                                          -> StartCalendarInterval: wall-clock times that survive
                                             a reboot. Anything that runs a few times a day or less;
                                             "*:10" is every hour at ten past.

Day words: mon tue wed thu fri sat sun, ranges like mon-fri, and lists like mon,wed,fri.
"""
from __future__ import annotations

import re
from typing import List, Union

DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]     # launchd Weekday: 0 = Sunday
_UNIT_S = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_EVERY = re.compile(r"^every\s+(\d+)\s*([smhd])$")
_AT = re.compile(r"^(?:(?P<days>[a-z,\-]+)\s+)?(?P<h>\d{1,2}|\*):(?P<m>\d{2})$")
LONGEST_INTERVAL_S = 2 * 3600     # beyond this, use clock times so the phase survives a reboot


class ScheduleError(ValueError):
    pass


def _days(text: str) -> List[int]:
    out: List[int] = []
    for part in text.split(","):
        if "-" in part:
            start, _, end = part.partition("-")
            if start not in DAYS or end not in DAYS:
                raise ScheduleError(f"unknown day range {part!r}")
            i, j = DAYS.index(start), DAYS.index(end)
            if j < i:
                raise ScheduleError(f"day range runs backwards: {part!r}")
            out.extend(range(i, j + 1))
        elif part in DAYS:
            out.append(DAYS.index(part))
        elif part == "daily":
            return []
        else:
            raise ScheduleError(f"unknown day {part!r}")
    return out


def to_launchd(schedule: Union[str, list]) -> dict:
    """``{"StartInterval": n}`` or ``{"StartCalendarInterval": [...]}`` for a schedule."""
    entries = [schedule] if isinstance(schedule, str) else list(schedule) if isinstance(schedule, tuple) else schedule
    if not isinstance(entries, list) or not entries or not all(isinstance(e, str) for e in entries):
        raise ScheduleError("schedule must be a string or a non-empty list of strings")
    entries = [e.strip().lower() for e in entries]

    every = [_EVERY.match(e) for e in entries]
    if any(every):
        if len(entries) != 1:
            raise ScheduleError("an `every` schedule stands alone")
        seconds = int(every[0].group(1)) * _UNIT_S[every[0].group(2)]
        if seconds < 60:
            raise ScheduleError("intervals under a minute are not schedules")
        if seconds > LONGEST_INTERVAL_S:
            raise ScheduleError(f"{entries[0]!r} is longer than every 2h: give clock times instead, "
                                "so a reboot does not move it")
        return {"StartInterval": seconds}

    slots = []
    for entry in entries:
        m = _AT.match(entry)
        if not m:
            raise ScheduleError(f"cannot read schedule entry {entry!r}")
        hour = None if m.group("h") == "*" else int(m.group("h"))
        minute = int(m.group("m"))
        if (hour is not None and hour > 23) or minute > 59:
            raise ScheduleError(f"no such time {entry!r}")
        at = {"Minute": minute} if hour is None else {"Hour": hour, "Minute": minute}
        days = _days(m.group("days")) if m.group("days") else []
        if days:
            slots.extend({**at, "Weekday": d} for d in days)
        else:
            slots.append(at)
    keys = [tuple(sorted(s.items())) for s in slots]
    if len(set(keys)) != len(keys):
        raise ScheduleError("schedule lists the same time twice")
    return {"StartCalendarInterval": slots}


def interval_s(schedule: Union[str, list]) -> int:
    """Longest normal gap between two firings; what "overdue" is measured against."""
    keys = to_launchd(schedule)
    if "StartInterval" in keys:
        return keys["StartInterval"]
    week = sorted({d * 86400 + h * 3600 + s["Minute"] * 60
                   for s in keys["StartCalendarInterval"]
                   for d in ([s["Weekday"]] if "Weekday" in s else range(7))
                   for h in ([s["Hour"]] if "Hour" in s else range(24))})
    gaps = [b - a for a, b in zip(week, week[1:])] + [week[0] + 7 * 86400 - week[-1]]
    return max(gaps)


def describe(schedule) -> str:
    """One line for people: ``every 15m`` or ``05:30, 17:30``."""
    if schedule is None:
        return ""
    return schedule if isinstance(schedule, str) else ", ".join(schedule)
