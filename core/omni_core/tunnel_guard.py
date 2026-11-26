"""Tunnel guard: every route behind the Cloudflare tunnel needs the key.

The dashboards bind to localhost and are published through a tunnel with no login of their own.
This ASGI middleware sits in front of the whole app, so no route, static file or future page can
be added unprotected. It uses only the standard library, so any dashboard can wear it:

    app.add_middleware(TunnelGuard)

A request is a *tunnel request* when it carries a header cloudflared adds to everything it
forwards (a local client cannot make cloudflared drop them). Tunnel requests must present the key
from ``~/.config/omni-system.key`` as a cookie. Opening any page once with ``?key=THE_KEY`` sets
that cookie and redirects to the same page without the key in the address. Requests from this
machine carry none of those headers and pass untouched. With no key file, every tunnel request
is refused: the guard fails closed.

Local processes on this machine, including other macOS accounts, can still reach the dashboard
directly on its localhost port; the guard protects the internet side only.
"""
from __future__ import annotations

import hmac
import json
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode

KEY_FILE = Path.home() / ".config" / "omni-system.key"
COOKIE = "omni_system_key"
COOKIE_MAX_AGE_S = 365 * 86400
TUNNEL_HEADERS = (b"cf-ray", b"cf-connecting-ip", b"x-forwarded-for")
LOG_EVERY_S = 60       # one log line per method and path per this long, so a poller cannot flood it
LOG_MAX_PATHS = 500

HTML_DENIED = (b"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
               b"<title>Key needed</title><body style='font:16px system-ui;padding:24px'>"
               b"<h1>This page needs a key</h1><p>Open this page once with <code>?key=YOUR_KEY</code> "
               b"on this device.</p>")


def read_key(path: Path = KEY_FILE) -> Optional[str]:
    try:
        key = Path(path).read_text().strip()
    except OSError:
        return None
    return key or None


def matches(candidate: Optional[str], key: Optional[str]) -> bool:
    return bool(candidate) and bool(key) and hmac.compare_digest(candidate.encode(), key.encode())


def came_through_tunnel(headers) -> bool:
    return any(name in TUNNEL_HEADERS for name, _ in headers)


def cookie_value(headers) -> Optional[str]:
    for name, value in headers:
        if name == b"cookie":
            jar = SimpleCookie()
            try:
                jar.load(value.decode("latin-1"))
            except Exception:
                return None
            morsel = jar.get(COOKIE)
            return morsel.value if morsel else None
    return None


def _header(headers, wanted: bytes) -> str:
    for name, value in headers:
        if name == wanted:
            return value.decode("latin-1")
    return ""


class TunnelGuard:
    def __init__(self, app, key_file: Path = KEY_FILE, clock: Callable[[], float] = time.time,
                 log: Callable[[str], None] = lambda line: print(line, file=sys.stderr)):
        self.app = app
        self.key_file = Path(key_file)
        self.clock = clock
        self.log = log
        self._logged: dict = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        if not came_through_tunnel(headers):
            return await self.app(scope, receive, send)

        key = read_key(self.key_file)
        if key and matches(cookie_value(headers), key):
            return await self.app(scope, receive, send)

        if scope["type"] == "websocket":
            self._note("WS", scope.get("path", ""), "no valid cookie")
            await receive()
            return await send({"type": "websocket.close", "code": 1008})

        method = scope.get("method", "GET")
        if method in ("GET", "HEAD") and key:
            params = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
            offered = [value for name, value in params if name == "key"]
            if offered:
                if matches(offered[0], key):
                    return await self._grant(scope, send, key, params)
                self._note(method, scope.get("path", ""), "wrong key")
                return await self._deny(scope, send, headers)

        self._note(method, scope.get("path", ""), "no key configured" if key is None else "no valid cookie")
        return await self._deny(scope, send, headers)

    async def _grant(self, scope, send, key: str, params) -> None:
        # A leading "//" would make the redirect target protocol-relative, i.e. another host.
        path = "/" + scope.get("path", "/").lstrip("/")
        rest = [(name, value) for name, value in params if name != "key"]
        location = path + ("?" + urlencode(rest) if rest else "")
        cookie = (f"{COOKIE}={key}; Max-Age={COOKIE_MAX_AGE_S}; Path=/; HttpOnly; Secure; SameSite=Lax")
        await send({"type": "http.response.start", "status": 303, "headers": [
            (b"location", location.encode("latin-1", "replace")), (b"set-cookie", cookie.encode()),
            (b"cache-control", b"no-store"), (b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

    async def _deny(self, scope, send, headers) -> None:
        wants_html = "text/html" in _header(headers, b"accept")
        body = HTML_DENIED if wants_html else json.dumps({"error": "key required"}).encode()
        kind = b"text/html; charset=utf-8" if wants_html else b"application/json"
        if scope.get("method") == "HEAD":
            body = b""
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", kind), (b"cache-control", b"no-store"),
            (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    def _note(self, method: str, path: str, reason: str) -> None:
        """Log a refusal, never the query string: a wrong key would end up in the log."""
        now = self.clock()
        if len(self._logged) > LOG_MAX_PATHS:
            self._logged.clear()
        last = self._logged.get((method, path))
        if last is not None and now - last < LOG_EVERY_S:
            return
        self._logged[(method, path)] = now
        self.log(f"tunnel_guard: refused {method} {path} ({reason})")
