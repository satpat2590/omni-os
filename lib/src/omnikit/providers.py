"""Text completion for domain automation. Third-party providers register omni.providers entry points."""
import json
import os
from importlib.metadata import entry_points
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


def complete(messages):
    provider = os.environ.get("OMNI_AI_PROVIDER", "offline")
    model = os.environ.get("OMNI_AI_MODEL", "")
    if provider == "offline":
        raise RuntimeError("Offline mode")
    if provider not in ("openrouter", "local"):
        (plugin,) = entry_points(group="omni.providers", name=provider)
        return plugin.load()(messages=messages, model=model)
    if not model:
        raise ValueError("Set OMNI_AI_MODEL to the model served by the provider")
    headers = {"Content-Type": "application/json"}
    if provider == "openrouter":
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers["Authorization"] = "Bearer " + os.environ["OPENROUTER_API_KEY"]
    else:
        base = os.environ.get("OMNI_LOCAL_BASE_URL", "http://127.0.0.1:8080/v1")
        if urlsplit(base).hostname not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("The local endpoint must use loopback")
        url = base.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 180}
    request = Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urlopen(request, timeout=8) as response:
        return json.load(response)["choices"][0]["message"]["content"]
