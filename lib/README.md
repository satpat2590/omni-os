# omnikit

Code shared across Omni and the domains built on it. It has one owner, here; each consumer keeps
only its own config, in a thin shim. It has no hard dependencies.

| Module | What it is |
|---|---|
| `omnikit.jev` | The Jev (TypeSafe System One) decisions client: a provider chain with per-provider keys, a fail-open `decide()`, a `requests` or stdlib transport, and a result hook. |
| `omnikit.jev_decider` | `Decision` and `JevDecider`: decisions as probability distributions, not just an argmax. |

A consumer builds a `JevConfig` (env prefix, providers, default timeout, transport, User-Agent,
`on_result` hook) and subclasses `JevClient`, so its own callers never change. `classify/` is the
example in this repo.

## Install

```bash
lib/install.sh [PYTHON ...]     # default: core/.venv/bin/python
```

This writes an `omnikit.pth` that points at `src/` into each interpreter's site-packages: no
network and no setuptools needed, and omnikit's own `tests/` can never shadow anyone else's.

## Tests

```bash
PYTHONPATH=lib/src core/.venv/bin/python -m pytest -q lib/tests
```
