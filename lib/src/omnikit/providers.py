"""Text completion for domain automation. Third-party providers register omni.providers entry points."""
import json
import os
from importlib.metadata import entry_points
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.parse import urlsplit


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint_url(base):
    url = urlsplit(base)
    local = url.hostname in ("127.0.0.1", "::1", "localhost")
    if (not url.hostname or url.username is not None or url.password is not None or url.query or
        url.fragment or not (url.scheme == "https" or (local and url.scheme == "http"))):
        raise ValueError("Use an HTTPS endpoint or a local loopback HTTP endpoint without embedded credentials.")
    return base.rstrip("/") + "/chat/completions"


def complete(messages):
    provider = os.environ.get("OMNI_AI_PROVIDER", "offline")
    model = os.environ.get("OMNI_AI_MODEL", "")
    if provider == "offline":
        raise RuntimeError("Offline mode")
    if provider not in ("openrouter", "local", "compatible"):
        (plugin,) = entry_points(group="omni.providers", name=provider)
        return plugin.load()(messages=messages, model=model)
    if not model:
        raise ValueError("Set OMNI_AI_MODEL to the model served by the provider")
    headers = {"Content-Type": "application/json"}
    if provider == "openrouter":
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers["Authorization"] = "Bearer " + os.environ["OPENROUTER_API_KEY"]
    elif provider == "compatible":
        url = endpoint_url(os.environ["OMNI_AI_BASE_URL"])
        key = os.environ.get("OMNI_AI_KEY")
        if key:
            headers["Authorization"] = "Bearer " + key
    else:
        base = os.environ.get("OMNI_LOCAL_BASE_URL", "http://127.0.0.1:8080/v1")
        if urlsplit(base).hostname not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("The local endpoint must use loopback")
        url = endpoint_url(base)
    payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 180}
    request = Request(url, data=json.dumps(payload).encode(), headers=headers)
    with build_opener(NoRedirect()).open(request, timeout=12) as response:
        return json.load(response)["choices"][0]["message"]["content"]
