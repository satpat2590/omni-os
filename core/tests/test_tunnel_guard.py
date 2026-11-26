"""The tunnel guard: local requests pass, tunnel requests need the key, and it fails closed."""
import asyncio

import pytest

from omni_core.tunnel_guard import COOKIE, TunnelGuard, matches, read_key

KEY = "k3y-for-tests_0123456789"
TUNNEL = [(b"cf-ray", b"abc123-AMS")]


async def inner_app(scope, receive, send):
    inner_app.calls += 1
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"inner"})


def drive(guard, *, path="/api/kanban", method="GET", headers=(), query=b"", scope_type="http"):
    """Run one request through ``guard``; returns (status, headers dict, body) or the ws close frame."""
    sent = []

    async def receive():
        return {"type": "websocket.connect"} if scope_type == "websocket" else {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    scope = {"type": scope_type, "path": path, "method": method, "headers": list(headers),
             "query_string": query}
    asyncio.run(guard(scope, receive, send))
    if scope_type == "websocket":
        return sent
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], {k.decode(): v.decode("latin-1") for k, v in start["headers"]}, body


@pytest.fixture
def guard(tmp_path):
    inner_app.calls = 0
    key_file = tmp_path / "key"
    key_file.write_text(KEY + "\n")
    lines = []
    g = TunnelGuard(inner_app, key_file=key_file, log=lines.append)
    g.lines, g.key_file_path = lines, key_file
    return g


def test_local_requests_pass_with_no_key(guard):
    status, _, body = drive(guard, headers=[(b"host", b"127.0.0.1:8600")])
    assert (status, body, inner_app.calls) == (200, b"inner", 1)


@pytest.mark.parametrize("header", [b"cf-ray", b"cf-connecting-ip", b"x-forwarded-for"])
def test_any_cloudflared_header_marks_a_tunnel_request(guard, header):
    status, _, _ = drive(guard, headers=[(header, b"x")])
    assert status == 401 and inner_app.calls == 0


def test_tunnel_request_without_the_cookie_is_refused_in_the_format_it_asked_for(guard):
    status, headers, body = drive(guard, headers=TUNNEL + [(b"accept", b"application/json")])
    assert status == 401 and b"key required" in body and headers["content-type"] == "application/json"
    assert headers["cache-control"] == "no-store"
    status, headers, body = drive(guard, headers=TUNNEL + [(b"accept", b"text/html,application/xhtml+xml")])
    assert status == 401 and body.startswith(b"<!doctype html>") and "text/html" in headers["content-type"]
    assert inner_app.calls == 0


def test_the_right_cookie_gets_through_and_a_wrong_one_does_not(guard):
    cookie = f"other=1; {COOKIE}={KEY}".encode()
    assert drive(guard, headers=TUNNEL + [(b"cookie", cookie)])[0] == 200
    assert drive(guard, headers=TUNNEL + [(b"cookie", f"{COOKIE}=nope".encode())])[0] == 401
    assert drive(guard, headers=TUNNEL + [(b"cookie", f"{COOKIE}=héllo".encode("latin-1"))])[0] == 401
    assert drive(guard, headers=TUNNEL + [(b"cookie", b"garbage;;;=")])[0] == 401


def test_the_key_in_the_query_sets_the_cookie_and_is_removed_from_the_address(guard):
    status, headers, _ = drive(guard, path="/system", headers=TUNNEL, query=f"key={KEY}&tab=2".encode())
    assert status == 303 and headers["location"] == "/system?tab=2"
    cookie = headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}={KEY};") and "HttpOnly" in cookie and "Secure" in cookie
    assert "SameSite=Lax" in cookie and "Max-Age=31536000" in cookie
    assert inner_app.calls == 0
    status, headers, _ = drive(guard, path="/x", headers=TUNNEL, query=f"key={KEY}".encode(), method="HEAD")
    assert status == 303 and headers["location"] == "/x"


def test_a_wrong_key_in_the_query_is_refused_without_a_cookie_and_never_logged(guard):
    status, headers, _ = drive(guard, headers=TUNNEL, query=b"key=wrong-key-value")
    assert status == 401 and "set-cookie" not in headers
    assert guard.lines and not any("wrong-key-value" in line or KEY in line for line in guard.lines)


def test_the_key_is_only_honoured_on_get_and_head(guard):
    status, headers, _ = drive(guard, method="POST", headers=TUNNEL, query=f"key={KEY}".encode())
    assert status == 401 and "set-cookie" not in headers


def test_a_leading_double_slash_cannot_turn_the_redirect_into_another_host(guard):
    for path in ("//evil.example/x", "///evil.example", "/\\evil.example"):
        _, headers, _ = drive(guard, path=path, headers=TUNNEL, query=f"key={KEY}".encode())
        assert headers["location"].startswith("/") and not headers["location"].startswith("//"), path


def test_no_key_file_refuses_every_tunnel_request_and_still_serves_local_ones(guard):
    guard.key_file_path.unlink()
    assert drive(guard, headers=TUNNEL + [(b"cookie", f"{COOKIE}={KEY}".encode())])[0] == 401
    assert drive(guard, headers=TUNNEL, query=f"key={KEY}".encode())[0] == 401
    assert any("no key configured" in line for line in guard.lines)
    assert drive(guard)[0] == 200


def test_an_empty_key_file_is_the_same_as_no_key(guard):
    guard.key_file_path.write_text("  \n")
    assert read_key(guard.key_file_path) is None
    assert drive(guard, headers=TUNNEL + [(b"cookie", f"{COOKIE}=".encode())])[0] == 401


def test_the_key_is_reread_each_request_so_rotating_it_logs_everyone_out(guard):
    cookie = [(b"cookie", f"{COOKIE}={KEY}".encode())]
    assert drive(guard, headers=TUNNEL + cookie)[0] == 200
    guard.key_file_path.write_text("a-new-key\n")
    assert drive(guard, headers=TUNNEL + cookie)[0] == 401


def test_websockets_from_the_tunnel_are_closed_without_the_cookie(guard):
    frames = drive(guard, scope_type="websocket", headers=TUNNEL)
    assert frames == [{"type": "websocket.close", "code": 1008}] and inner_app.calls == 0
    assert drive(guard, scope_type="websocket", headers=[]) == [] and inner_app.calls == 1


def test_lifespan_passes_through(guard):
    asyncio.run(guard({"type": "lifespan"}, None, None))
    assert inner_app.calls == 1


def test_refusals_are_logged_once_a_minute_per_path_and_carry_no_query(tmp_path):
    inner_app.calls = 0
    key_file = tmp_path / "key"
    key_file.write_text(KEY)
    now, lines = [1000.0], []
    g = TunnelGuard(inner_app, key_file=key_file, clock=lambda: now[0], log=lines.append)
    for _ in range(50):
        drive(g, path="/api/status", headers=TUNNEL, query=b"x=secret")
    assert lines == ["tunnel_guard: refused GET /api/status (no valid cookie)"]
    now[0] += 61
    drive(g, path="/api/status", headers=TUNNEL)
    drive(g, path="/api/kanban", headers=TUNNEL)
    assert len(lines) == 3


def test_matches_is_false_for_empty_values():
    assert not matches("", KEY) and not matches(KEY, "") and not matches(None, KEY) and matches(KEY, KEY)
