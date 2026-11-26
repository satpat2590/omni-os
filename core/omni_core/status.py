"""``omni status``: is every registered service up, and who fires each job today.

A service is healthy when launchd reports it running and, if it declares a port, the port accepts
a connection on localhost. Jobs are listed by who starts them: `omni run` (enabled in the
registry) or launchd directly (registered, not yet cut over).
"""
from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

from .registry import Registry, Service


@dataclass
class ServiceState:
    name: str
    domain: str
    launchd: str
    state: str               # running | not running | not loaded | unknown
    port: Optional[int]
    port_open: Optional[bool]

    @property
    def ok(self) -> bool:
        return self.state == "running" and self.port_open is not False


def launchd_state(label: str) -> str:
    try:
        proc = subprocess.run(["launchctl", "print", f"system/{label}"], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if proc.returncode != 0:
        return "not loaded"
    for line in proc.stdout.splitlines():
        if line.startswith("\tstate = "):
            return line.split("= ", 1)[1].strip()
    return "unknown"


def port_open(port: int) -> bool:
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            continue
    return False


def service_states(registry: Registry, *, state_of: Callable[[str], str] = launchd_state,
                   is_open: Callable[[int], bool] = port_open) -> list:
    out = []
    for service in registry.services.values():
        out.append(_state(service, state_of, is_open))
    return out


def _state(service: Service, state_of, is_open) -> ServiceState:
    state = state_of(service.launchd)
    opened = is_open(service.port) if service.port is not None and state == "running" else None
    return ServiceState(name=service.name, domain=service.domain, launchd=service.launchd,
                        state=state, port=service.port, port_open=opened)


def render(registry: Registry, states: list) -> tuple:
    """Lines to print and the exit code (1 when any service is unhealthy)."""
    lines = [f"services ({len(states)})"]
    for s in sorted(states, key=lambda s: (s.domain, s.name)):
        port = "" if s.port is None else f"  port {s.port} {'open' if s.port_open else 'CLOSED'}"
        lines.append(f"  {'ok  ' if s.ok else 'DOWN'} {s.domain:<9} {s.name:<20} {s.state}{port}")
    by_domain: dict = {}
    for job in registry.jobs.values():
        counts = by_domain.setdefault(job.domain, {"omni": 0, "launchd": 0, "off": 0})
        counts["omni" if job.enabled else ("launchd" if job.launchd else "off")] += 1
    lines.append(f"jobs ({len(registry.jobs)})")
    for domain in sorted(by_domain):
        c = by_domain[domain]
        lines.append(f"  {domain:<9} {c['omni']} through omni run, {c['launchd']} fired by launchd "
                     f"directly, {c['off']} disabled")
    down = [s.name for s in states if not s.ok]
    if down:
        lines.append(f"DOWN: {', '.join(sorted(down))}")
    return lines, 1 if down else 0
