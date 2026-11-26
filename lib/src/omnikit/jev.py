"""The one Jev (TypeSafe "System One") decisions client for Omni OS.

Jev does not generate text. It evaluates typed *questions* against a *state*
and returns calibrated probabilities (``noul`` / ``choice`` / ``score``).
``JevClient.decide()`` returns the ``answers`` dict, or ``None`` when Jev is
disabled or every provider fails. It never raises, so callers degrade to their
own deterministic floor (fail-open). Jev is advisory everywhere it is used.

Each domain keeps a thin shim that builds a ``JevConfig`` (its env prefix,
default timeout, provider set, key sources, transport and an optional result
hook) and subclasses ``JevClient``. The shims keep their own env var names and
constructor kwargs, so no caller changes when this module does.

Providers are tried in order and the first that yields answers wins. Each
provider carries its own key, model and endpoint, so a TypeSafe key is never
sent to OpenRouter and the reverse.

No hard dependencies: ``transport="requests"`` uses ``requests`` (missing →
``None``), ``"urllib"`` uses the stdlib, and ``"auto"`` prefers ``requests`` and
falls back to the stdlib. The stdlib path always sends a browser-like
User-Agent, because Cloudflare (error 1010) bans python-urllib's default one.

Env read for a config with ``env_prefix="X"`` (``X_TIMEOUT`` only when the
caller passes no explicit timeout):
    X_PROVIDER — comma-separated provider order (default ``config.default_order``)
    X_ENABLED  — "0"/"false"/"no"/"off"/"" disables even with a key (default on)
    X_TIMEOUT  — per-call seconds (default ``config.default_timeout``)
Per-provider key/model/endpoint env names are listed on each ``Provider``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

NATIVE_MODEL = "jev-latest"
NATIVE_BASE_URL = "https://api.typesafe.ai/v1/systemone"
OPENROUTER_MODEL = "~typesafe/jev-latest"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_ORDER = "native,openrouter"
DEFAULT_TIMEOUT = 15.0
# Cloudflare error 1010 bans python-urllib's default User-Agent.
DEFAULT_URLLIB_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) omnikit-jev/1.0"

_FALSY = ("0", "false", "no", "off", "")

ResultHook = Callable[[str, str], None]  # (state "ok" | "error", detail)


@dataclass(frozen=True)
class Provider:
    """One decisions endpoint.

    ``key_env`` / ``model_env`` / ``base_url_env`` are env names tried in order;
    the first non-empty value wins. ``static_key`` is for loopback services that
    take no auth (a non-empty placeholder so the provider isn't skipped).
    """

    name: str
    model: str
    base_url: str
    key_env: Tuple[str, ...] = ()
    static_key: Optional[str] = None
    model_env: Tuple[str, ...] = ()
    base_url_env: Tuple[str, ...] = ()


@dataclass(frozen=True)
class JevConfig:
    """Everything that differs between the domains' Jev clients.

    env_prefix         — reads ``{prefix}_PROVIDER`` / ``_ENABLED`` / ``_TIMEOUT``; None reads none.
    providers          — the provider set; order strings may only name these.
    default_order      — used when neither the kwarg nor the env names a provider.
    default_timeout    — seconds, when neither the kwarg nor ``{prefix}_TIMEOUT`` sets one.
    key_files          — ``KEY=value`` files consulted when a key env var is empty
                         (values are stripped, env first, then each file in order).
    explicit_key_scope — "primary": an explicit ``api_key`` applies to the first provider only
                         (``None`` means "not given"); "all": it applies to every provider and
                         an empty one falls back to env.
    transport          — "requests" | "urllib" | "auto".
    requests_module    — returns the ``requests`` module to use (lets a shim keep a patchable
                         module attribute); default imports ``requests`` at call time.
    user_agent         — sent on both transports when set; the urllib path falls back to
                         ``DEFAULT_URLLIB_USER_AGENT``.
    on_result          — called with ("ok", detail) after a provider answers and with
                         ("error", detail) when all providers fail; exceptions are swallowed.
    logger_name        — logger to report on (shims pass their own ``__name__``).
    """

    env_prefix: Optional[str] = None
    providers: Tuple[Provider, ...] = field(default_factory=lambda: standard_providers(None))
    default_order: str = DEFAULT_ORDER
    default_timeout: float = DEFAULT_TIMEOUT
    key_files: Tuple[str, ...] = ()
    explicit_key_scope: str = "primary"
    transport: str = "auto"
    requests_module: Optional[Callable[[], Any]] = None
    user_agent: Optional[str] = None
    on_result: Optional[ResultHook] = None
    logger_name: str = __name__

    def env(self, suffix: str) -> Optional[str]:
        return f"{self.env_prefix}_{suffix}" if self.env_prefix else None


def standard_providers(
    env_prefix: Optional[str],
    key_override_env: Optional[str] = None,
) -> Tuple[Provider, Provider]:
    """The native + OpenRouter pair.

    With an ``env_prefix``, ``{prefix}_MODEL`` and ``{prefix}_BASE_URL`` override
    the model / endpoint of whichever of the two is used. ``key_override_env``
    (e.g. ``VELTIOSI_JEV_API_KEY``) is consulted before each provider's own key.
    """
    model_env = (f"{env_prefix}_MODEL",) if env_prefix else ()
    url_env = (f"{env_prefix}_BASE_URL",) if env_prefix else ()
    override = (key_override_env,) if key_override_env else ()
    return (
        Provider("native", NATIVE_MODEL, NATIVE_BASE_URL, override + ("TYPESAFE_API_KEY",), None, model_env, url_env),
        Provider("openrouter", OPENROUTER_MODEL, OPENROUTER_BASE_URL, override + ("OPENROUTER_API_KEY",), None, model_env, url_env),
    )


def env_bool(name: Optional[str], default: bool) -> bool:
    raw = os.getenv(name) if name else None
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSY


def read_key_file(path: str) -> Dict[str, str]:
    """``KEY=value`` pairs from ``path`` (best-effort; missing file → {})."""
    out: Dict[str, str] = {}
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def parse_order(raw: Optional[str], known: Sequence[str], default: str) -> List[str]:
    """Comma-separated provider names, unknown ones dropped; empty → ``default``."""
    text = (raw or default).strip().lower()
    order = [p for p in (x.strip() for x in text.split(",")) if p in known]
    if not order:
        order = [p for p in default.split(",") if p in known]
    return order


class JevClient:
    """Fail-open wrapper around the Jev Decisions API, configured by a ``JevConfig``.

    Explicit ``model`` / ``base_url`` apply to the primary provider only; later
    providers use env/defaults. ``api_key`` follows ``config.explicit_key_scope``.
    """

    def __init__(
        self,
        config: Optional[JevConfig] = None,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
        provider: Optional[str] = None,
    ) -> None:
        cfg = config or JevConfig()
        self.config = cfg
        self._log = logging.getLogger(cfg.logger_name)
        self._file_keys: Optional[Dict[str, str]] = None

        by_name = {p.name: p for p in cfg.providers}
        prov_env = cfg.env("PROVIDER")
        order = parse_order(provider or (os.getenv(prov_env) if prov_env else None), list(by_name), cfg.default_order)
        self.provider = order[0]
        self._order = order

        chain: List[Tuple[Optional[str], str, str]] = []
        for i, name in enumerate(order):
            p = by_name[name]
            key = self._resolve_key(p)
            m = self._first_env(p.model_env) or p.model
            u = self._first_env(p.base_url_env) or p.base_url
            if cfg.explicit_key_scope == "all":
                key = api_key or key
            elif i == 0 and api_key is not None:
                key = api_key
            if i == 0:
                m = model if model is not None else m
                u = base_url if base_url is not None else u
            chain.append((key, m, u))
        self._chain = chain
        # Primary provider, for introspection.
        self.api_key, self.model, self.base_url = chain[0]

        if timeout is not None:
            self.timeout = float(timeout)
        else:
            t_env = cfg.env("TIMEOUT")
            try:
                self.timeout = float(os.getenv(t_env, cfg.default_timeout) if t_env else cfg.default_timeout)
            except (TypeError, ValueError):
                self.timeout = float(cfg.default_timeout)

        if enabled is None:
            enabled = env_bool(cfg.env("ENABLED"), True)
        self._enabled = bool(enabled)

        # Versioned model + provider that answered the last call (auditing).
        self.last_model: Optional[str] = None
        self.last_provider: Optional[str] = None

    # ---- key / env resolution -------------------------------------------------

    def _lookup(self, name: str) -> Optional[str]:
        if not self.config.key_files:
            return os.getenv(name)
        val = os.environ.get(name, "").strip()
        if val:
            return val
        if self._file_keys is None:
            merged: Dict[str, str] = {}
            for path in reversed(self.config.key_files):  # earlier files win
                merged.update(read_key_file(path))
            self._file_keys = merged
        return self._file_keys.get(name, "").strip()

    def _resolve_key(self, p: Provider) -> Optional[str]:
        if p.static_key is not None:
            return p.static_key
        val: Optional[str] = None
        for name in p.key_env:
            val = self._lookup(name)
            if val:
                return val
        return val

    @staticmethod
    def _first_env(names: Sequence[str]) -> Optional[str]:
        for name in names:
            val = os.getenv(name)
            if val:
                return val
        return None

    # ---- public API ------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """True when enabled by flag AND at least one provider has a key."""
        return self._enabled and any(key for key, _, _ in self._chain)

    def decide(self, state: Any, questions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Evaluate ``questions`` against ``state``; return the ``answers`` dict.

        ``state`` may be a str, dict, or list (passed through verbatim).
        ``questions`` is ``{name: {type, instructions, criteria?}}`` where type
        is one of ``noul`` | ``choice`` | ``score``.

        Returns ``None`` (never raises) when disabled or every provider fails.
        """
        try:
            return self._decide(state, questions)
        except Exception as e:  # noqa: BLE001 — the contract is "never raises"
            self._log.warning(f"JevClient: unexpected failure — {e}")
            return None

    def _decide(self, state: Any, questions: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        log = self._log
        if not self.enabled:
            flag = self.config.env("ENABLED")
            log.debug(f"JevClient: disabled (no key or {flag + '=0' if flag else 'enabled=False'})")
            return None

        post = self._transport()
        if post is None:
            return None

        for i, (key, model, base_url) in enumerate(self._chain):
            if not key:
                continue
            name = self._order[i]
            payload = {"model": model, "state": state, "questions": questions}
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            t0 = time.monotonic()
            try:
                status, body, parse = post(base_url, headers, payload)
            except Exception as e:  # noqa: BLE001 — try the next provider
                log.warning(f"JevClient[{name}]: request failed after {time.monotonic() - t0:.2f}s — {e}")
                continue

            elapsed = time.monotonic() - t0
            if status != 200:
                snippet = (body() or "")[:200].replace("\n", " ")
                log.warning(f"JevClient[{name}]: HTTP {status} in {elapsed:.2f}s — {snippet}")
                continue

            try:
                data = parse()
            except Exception as e:  # noqa: BLE001
                log.warning(f"JevClient[{name}]: non-JSON response — {e}")
                continue

            if not isinstance(data, dict):
                log.warning(f"JevClient[{name}]: response must be a JSON object")
                continue

            answers = data.get("answers")
            if not isinstance(answers, dict):
                log.warning(f"JevClient[{name}]: response missing 'answers' object")
                continue

            self.last_model = data.get("model")
            self.last_provider = name
            log.info(f"JevClient[{name}]: {self.last_model or model} answered {len(answers)} question(s) in {elapsed:.2f}s")
            self._hook("ok", f"{self.last_model or model} via {name}")
            return answers

        log.warning(f"JevClient: all providers failed ({', '.join(self._order)})")
        self._hook("error", f"all providers failed ({', '.join(self._order)})")
        return None

    def _hook(self, state: str, detail: str) -> None:
        if self.config.on_result is None:
            return
        try:
            self.config.on_result(state, detail)
        except Exception:  # noqa: BLE001 — a result hook can never fail a decision
            pass

    # ---- transports ------------------------------------------------------------
    # Each returns post(url, headers, payload) -> (status, body_text(), parse_json()).

    def _transport(self):
        mode = self.config.transport
        if mode in ("requests", "auto"):
            req = self._requests()
            if req is not None:
                return self._requests_post(req)
            if mode == "requests":
                self._log.warning("JevClient: 'requests' unavailable — degrading to None")
                return None
        return self._urllib_post

    def _requests(self):
        try:
            if self.config.requests_module is not None:
                return self.config.requests_module()
            import requests  # lazy — no hard dependency

            return requests
        except Exception:  # noqa: BLE001
            return None

    def _requests_post(self, requests_mod):
        ua = self.config.user_agent

        def post(url, headers, payload):
            if ua:
                headers = dict(headers, **{"User-Agent": ua})
            resp = requests_mod.post(url, headers=headers, json=payload, timeout=self.timeout)
            return resp.status_code, (lambda: resp.text), resp.json

        return post

    def _urllib_post(self, url, headers, payload):
        import urllib.error
        import urllib.request

        hdrs = dict(headers, **{"User-Agent": self.config.user_agent or DEFAULT_URLLIB_USER_AGENT})
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                status = getattr(r, "status", None) or 200
                raw = r.read()
        except urllib.error.HTTPError as e:
            try:
                text = e.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                text = ""
            return e.code, (lambda: text), (lambda: None)
        return status, (lambda: raw.decode("utf-8", "replace")), (lambda: json.loads(raw))
