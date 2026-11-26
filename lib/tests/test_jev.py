"""omnikit.jev — the one Jev client. No network: transports are faked."""

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omnikit import jev  # noqa: E402
from omnikit.jev import JevClient, JevConfig, Provider, standard_providers  # noqa: E402

ANSWERS = {"q": {"type": "noul", "noul": 0.9}}
ENV = ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "T_JEV_PROVIDER", "T_JEV_ENABLED", "T_JEV_TIMEOUT",
       "T_JEV_MODEL", "T_JEV_BASE_URL", "T_JEV_API_KEY")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)


class Resp:
    def __init__(self, status=200, data=None, text="", bad_json=False):
        self.status_code, self._data, self.text, self._bad = status, data, text, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._data


class FakeRequests:
    """Records calls; ``script`` maps url -> Resp | Exception (or a list consumed in order)."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        r = self.script[url]
        if isinstance(r, Exception):
            raise r
        return r


def cfg(fake=None, **kw):
    base = dict(env_prefix="T_JEV", providers=standard_providers("T_JEV", key_override_env="T_JEV_API_KEY"),
                transport="requests", requests_module=(lambda: fake) if fake is not None else None)
    base.update(kw)
    return JevConfig(**base)


def keys(monkeypatch, ts="ts-key", orr="or-key"):
    if ts:
        monkeypatch.setenv("TYPESAFE_API_KEY", ts)
    if orr:
        monkeypatch.setenv("OPENROUTER_API_KEY", orr)


# ---- provider order -----------------------------------------------------------

def test_default_order_is_native_then_openrouter(monkeypatch):
    keys(monkeypatch)
    c = JevClient(cfg())
    assert c._order == ["native", "openrouter"] and c.provider == "native"
    assert c.base_url == jev.NATIVE_BASE_URL and c.model == jev.NATIVE_MODEL and c.api_key == "ts-key"


def test_env_order_and_kwarg_override(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("T_JEV_PROVIDER", "openrouter, native")
    assert JevClient(cfg())._order == ["openrouter", "native"]
    assert JevClient(cfg(), provider="native")._order == ["native"]


def test_unknown_providers_fall_back_to_default_order(monkeypatch):
    keys(monkeypatch)
    assert JevClient(cfg(), provider="bogus,also-bogus")._order == ["native", "openrouter"]
    monkeypatch.setenv("T_JEV_PROVIDER", "   ")
    assert JevClient(cfg())._order == ["native", "openrouter"]


def test_first_provider_that_answers_wins(monkeypatch):
    keys(monkeypatch)
    fake = FakeRequests({jev.NATIVE_BASE_URL: Resp(200, {"model": "jev-1.13.0", "answers": ANSWERS}),
                         jev.OPENROUTER_BASE_URL: Resp(500)})
    c = JevClient(cfg(fake))
    assert c.decide("s", {"q": {}}) == ANSWERS
    assert [x["url"] for x in fake.calls] == [jev.NATIVE_BASE_URL]
    assert (c.last_provider, c.last_model) == ("native", "jev-1.13.0")


# ---- fallthrough ----------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    Resp(503, text="down"),                       # HTTP error
    RuntimeError("connection reset"),             # transport error
    Resp(200, bad_json=True),                     # non-JSON body
    Resp(200, ["not", "an", "object"]),           # JSON but not an object
    Resp(200, {"model": "jev-1.13"}),             # missing answers
    Resp(200, {"answers": ["wrong", "type"]}),    # answers not a dict
])
def test_native_failure_falls_through_to_openrouter(monkeypatch, bad):
    keys(monkeypatch)
    fake = FakeRequests({jev.NATIVE_BASE_URL: bad,
                         jev.OPENROUTER_BASE_URL: Resp(200, {"model": "typesafe/jev", "answers": ANSWERS})})
    c = JevClient(cfg(fake))
    assert c.decide("s", {"q": {}}) == ANSWERS
    assert c.last_provider == "openrouter"
    assert [x["url"] for x in fake.calls] == [jev.NATIVE_BASE_URL, jev.OPENROUTER_BASE_URL]


def test_all_providers_failing_returns_none(monkeypatch):
    keys(monkeypatch)
    fake = FakeRequests({jev.NATIVE_BASE_URL: Resp(500), jev.OPENROUTER_BASE_URL: Resp(200, bad_json=True)})
    c = JevClient(cfg(fake))
    assert c.decide("s", {"q": {}}) is None
    assert c.last_provider is None


def test_provider_without_key_is_skipped(monkeypatch):
    keys(monkeypatch, ts=None)
    fake = FakeRequests({jev.OPENROUTER_BASE_URL: Resp(200, {"answers": ANSWERS})})
    assert JevClient(cfg(fake)).decide("s", {}) == ANSWERS
    assert [x["url"] for x in fake.calls] == [jev.OPENROUTER_BASE_URL]


# ---- disabled ---------------------------------------------------------------------

def test_disabled_without_any_key():
    fake = FakeRequests({})
    c = JevClient(cfg(fake))
    assert not c.enabled and c.decide("s", {}) is None and fake.calls == []


@pytest.mark.parametrize("flag", ["0", "false", "off", "no", ""])
def test_disabled_by_env_flag(monkeypatch, flag):
    keys(monkeypatch)
    monkeypatch.setenv("T_JEV_ENABLED", flag)
    fake = FakeRequests({})
    c = JevClient(cfg(fake))
    assert not c.enabled and c.decide("s", {}) is None and fake.calls == []


def test_disabled_by_kwarg_beats_env(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("T_JEV_ENABLED", "1")
    assert not JevClient(cfg(), enabled=False).enabled
    monkeypatch.setenv("T_JEV_ENABLED", "0")
    assert JevClient(cfg(), enabled=True).enabled


def test_requests_transport_missing_returns_none(monkeypatch):
    keys(monkeypatch)
    c = JevClient(cfg(requests_module=lambda: None))
    assert c.enabled and c.decide("s", {}) is None


# ---- key isolation ---------------------------------------------------------------

def test_each_provider_gets_only_its_own_key(monkeypatch):
    keys(monkeypatch)
    fake = FakeRequests({jev.NATIVE_BASE_URL: Resp(500), jev.OPENROUTER_BASE_URL: Resp(500)})
    JevClient(cfg(fake)).decide("s", {})
    sent = {x["url"]: x["headers"]["Authorization"] for x in fake.calls}
    assert sent == {jev.NATIVE_BASE_URL: "Bearer ts-key", jev.OPENROUTER_BASE_URL: "Bearer or-key"}


def test_explicit_key_primary_scope_applies_to_first_provider_only(monkeypatch):
    keys(monkeypatch)
    fake = FakeRequests({jev.NATIVE_BASE_URL: Resp(500), jev.OPENROUTER_BASE_URL: Resp(500)})
    JevClient(cfg(fake), api_key="explicit").decide("s", {})
    assert [x["headers"]["Authorization"] for x in fake.calls] == ["Bearer explicit", "Bearer or-key"]


def test_explicit_key_all_scope_applies_to_every_provider(monkeypatch):
    keys(monkeypatch)
    c = JevClient(cfg(explicit_key_scope="all"), api_key="explicit")
    assert [k for k, _, _ in c._chain] == ["explicit", "explicit"]
    c = JevClient(cfg(explicit_key_scope="all"), api_key="")  # empty falls back to env
    assert [k for k, _, _ in c._chain] == ["ts-key", "or-key"]


def test_key_override_env_wins_for_every_provider(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("T_JEV_API_KEY", "override")
    assert [k for k, _, _ in JevClient(cfg())._chain] == ["override", "override"]


def test_unrelated_env_key_never_used(monkeypatch):
    # Only the env names listed on a provider count; a stray *_API_KEY does not.
    monkeypatch.setenv("SOMETHING_JEV_API_KEY", "stray")
    keys(monkeypatch, orr=None)
    c = JevClient(cfg(providers=standard_providers("T_JEV")))
    assert [k for k, _, _ in c._chain] == ["ts-key", None]


def test_key_file_fallback_and_env_precedence(monkeypatch, tmp_path):
    f = tmp_path / ".env"
    f.write_text('# c\nTYPESAFE_API_KEY="file-ts"\nOPENROUTER_API_KEY=file-or\n')
    c = JevClient(cfg(key_files=(str(f),)))
    assert [k for k, _, _ in c._chain] == ["file-ts", "file-or"]
    monkeypatch.setenv("TYPESAFE_API_KEY", "  env-ts  ")
    c = JevClient(cfg(key_files=(str(f),)))
    assert [k for k, _, _ in c._chain] == ["env-ts", "file-or"]
    assert JevClient(cfg(key_files=(str(tmp_path / "missing"),)))._chain[1][0] == ""


def test_static_key_provider():
    p = Provider("loop", "m", "http://127.0.0.1:1/", static_key="local")
    c = JevClient(JevConfig(providers=(p,), default_order="loop"))
    assert c.enabled and c.api_key == "local"


# ---- model / url / timeout ----------------------------------------------------

def test_explicit_model_and_url_apply_to_primary_only(monkeypatch):
    keys(monkeypatch)
    c = JevClient(cfg(), model="m-x", base_url="http://x/")
    assert c._chain[0][1:] == ("m-x", "http://x/")
    assert c._chain[1][1:] == (jev.OPENROUTER_MODEL, jev.OPENROUTER_BASE_URL)


def test_prefix_model_env_applies_to_both(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("T_JEV_MODEL", "jev-pinned")
    assert [m for _, m, _ in JevClient(cfg())._chain] == ["jev-pinned", "jev-pinned"]


def test_timeout_kwarg_env_default_and_bad_env(monkeypatch):
    assert JevClient(cfg(default_timeout=7)).timeout == 7.0
    monkeypatch.setenv("T_JEV_TIMEOUT", "3.5")
    assert JevClient(cfg()).timeout == 3.5
    assert JevClient(cfg(), timeout=1).timeout == 1.0
    monkeypatch.setenv("T_JEV_TIMEOUT", "soon")
    assert JevClient(cfg(default_timeout=9)).timeout == 9.0


def test_timeout_is_passed_to_transport(monkeypatch):
    keys(monkeypatch, orr=None)
    fake = FakeRequests({jev.NATIVE_BASE_URL: Resp(200, {"answers": ANSWERS})})
    JevClient(cfg(fake), timeout=4).decide("s", {})
    assert fake.calls[0]["timeout"] == 4.0


# ---- result hook ----------------------------------------------------------------

def test_result_hook_ok_and_error(monkeypatch):
    keys(monkeypatch, orr=None)
    seen = []
    hook = lambda state, detail: seen.append((state, detail))  # noqa: E731
    ok = FakeRequests({jev.NATIVE_BASE_URL: Resp(200, {"model": "jev-1.13.0", "answers": ANSWERS})})
    JevClient(cfg(ok, on_result=hook)).decide("s", {})
    bad = FakeRequests({jev.NATIVE_BASE_URL: Resp(500)})
    JevClient(cfg(bad, on_result=hook)).decide("s", {})
    assert seen == [("ok", "jev-1.13.0 via native"), ("error", "all providers failed (native, openrouter)")]


def test_result_hook_not_called_when_disabled():
    seen = []
    JevClient(cfg(FakeRequests({}), on_result=lambda *a: seen.append(a))).decide("s", {})
    assert seen == []


def test_raising_hook_never_fails_a_decision(monkeypatch):
    keys(monkeypatch, orr=None)

    def hook(*_):
        raise RuntimeError("journal down")

    fake = FakeRequests({jev.NATIVE_BASE_URL: Resp(200, {"answers": ANSWERS})})
    assert JevClient(cfg(fake, on_result=hook)).decide("s", {}) == ANSWERS


# ---- transports -----------------------------------------------------------------

class UrlResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_urllib_transport_sends_browser_user_agent(monkeypatch):
    keys(monkeypatch, orr=None)
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["ua"] = req.get_header("User-agent")
        seen["auth"] = req.get_header("Authorization")
        seen["body"] = json.loads(req.data)
        seen["timeout"] = timeout
        return UrlResp(json.dumps({"answers": ANSWERS}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert JevClient(cfg(transport="urllib"), timeout=2).decide({"a": 1}, {"q": {}}) == ANSWERS
    assert seen["ua"] == jev.DEFAULT_URLLIB_USER_AGENT and "urllib" not in seen["ua"].lower()
    assert seen["auth"] == "Bearer ts-key" and seen["body"]["state"] == {"a": 1} and seen["timeout"] == 2.0
    JevClient(cfg(transport="urllib", user_agent="custom/1")).decide("s", {})
    assert seen["ua"] == "custom/1"


def test_urllib_http_error_falls_through(monkeypatch):
    keys(monkeypatch)

    def fake_urlopen(req, timeout=0):
        if req.full_url == jev.NATIVE_BASE_URL:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b"error code: 1010"))
        return UrlResp(json.dumps({"answers": ANSWERS}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = JevClient(cfg(transport="urllib"))
    assert c.decide("s", {}) == ANSWERS and c.last_provider == "openrouter"


def test_urllib_non_json_returns_none(monkeypatch):
    keys(monkeypatch, orr=None)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: UrlResp(b"<html>"))
    assert JevClient(cfg(transport="urllib")).decide("s", {}) is None


def test_auto_prefers_requests_and_falls_back_to_urllib(monkeypatch):
    keys(monkeypatch, orr=None)
    fake = FakeRequests({jev.NATIVE_BASE_URL: Resp(200, {"answers": ANSWERS})})
    assert JevClient(cfg(fake, transport="auto")).decide("s", {}) == ANSWERS and len(fake.calls) == 1
    assert "User-Agent" not in fake.calls[0]["headers"]  # requests path keeps its own UA unless configured
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: UrlResp(json.dumps({"answers": ANSWERS}).encode()))
    assert JevClient(cfg(transport="auto", requests_module=lambda: None)).decide("s", {}) == ANSWERS


def test_never_raises_on_unserialisable_state(monkeypatch):
    keys(monkeypatch, orr=None)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: UrlResp(b"{}"))
    assert JevClient(cfg(transport="urllib")).decide(object(), {}) is None


def test_default_config_is_usable(monkeypatch):
    keys(monkeypatch)
    c = JevClient()
    assert c._order == ["native", "openrouter"] and c.timeout == jev.DEFAULT_TIMEOUT and c.enabled
