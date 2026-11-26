"""Fail-open Jev (TypeSafe System One) client — never raises.

Thin shim over the one shared implementation, ``omnikit.jev`` (in
``~/omni/lib``). This module owns only the classify layer's config: the
``OMNI_JEV_*`` env names, the stdlib
transport and its User-Agent, and the ``provider_order`` kwarg.

Jev returns typed decisions (`noul` / `choice` / `score`), not text. ``decide()``
NEVER raises: on any failure it returns ``None`` so callers degrade to a
deterministic floor.

Providers (tried in order): native → openrouter.

Environment:
    OMNI_JEV_PROVIDER — comma-separated provider order; default "native,openrouter"
    OMNI_JEV_ENABLED  — "0"/"false"/"off" disables even with a key (default on)
    TYPESAFE_API_KEY  — native provider
    OPENROUTER_API_KEY— openrouter provider
"""

from __future__ import annotations

from typing import Optional

from omnikit import jev as _jev

NATIVE_URL = _jev.NATIVE_BASE_URL
NATIVE_MODEL = _jev.NATIVE_MODEL
OPENROUTER_URL = _jev.OPENROUTER_BASE_URL
OPENROUTER_MODEL = _jev.OPENROUTER_MODEL

_PROVIDERS = ("native", "openrouter")

CONFIG = _jev.JevConfig(
    env_prefix="OMNI_JEV",
    # No model / endpoint env overrides here (there never were).
    providers=_jev.standard_providers(None),
    default_order="native,openrouter",
    default_timeout=15.0,
    key_files=(),
    explicit_key_scope="all",
    transport="urllib",
    # Cloudflare (error 1010) bans the default python-urllib UA
    user_agent="Mozilla/5.0 (X11; Linux x86_64) omni-classify/1.0",
    logger_name=__name__,
)


class JevClient(_jev.JevClient):
    """Thin fail-open wrapper around the Jev Decisions API (Omni classify config).

    ``decide()`` returns the ``answers`` dict or ``None`` (never raises) when
    disabled or on any transport / HTTP / parse failure.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider_order: Optional[str] = None,
        timeout: float = 15.0,
        enabled: Optional[bool] = None,
    ) -> None:
        super().__init__(CONFIG, api_key=api_key, timeout=timeout, enabled=enabled, provider=provider_order)
