---
name: omni-test
description: Which Omni OS test suites exist, what each needs (local Postgres, models, interpreters), and how to run them in the testing ground, in an installed checkout, or the way CI does. Use before committing, before review, and when a test fails.
---

# Testing Omni OS

Every suite runs offline, without secrets. Suites that need a database create a brand-new one on a
**local** server you name, and drop it afterwards. The fixtures refuse any non-local host, so a
test can never reach production.

## The quick way, in an installed checkout

```bash
./install.sh test        # Atma API, core, classify, lib, root tests and both SDLC suites
```

This uses the checkout's own private cluster (`.omni-local/`) and venvs. It needs a prior
`./install.sh`.

## Suite by suite

From the repository root. `PY` is core's interpreter: `core/.venv/bin/python`, created with
`uv venv --python 3.12 core/.venv && uv pip install --python core/.venv/bin/python -e "core[dev]" -e lib numpy scikit-learn`.

| Suite | Command | Needs |
|---|---|---|
| core (registry, runner, ledger, launchd, **board**) | `(cd core && OMNI_TEST_SERVER_URL=... .venv/bin/python -m pytest -q)` | Postgres for the board tests (skip without it) |
| Atma API | `(cd atma/api && ATMA_TEST_SERVER_URL=... .venv/bin/python -m pytest -q)` | its own venv (`-r requirements-dev.txt -e ../../lib`); Postgres; `ATMA_TEST_NLP_DIR` for the NLP tests (skip without) |
| classify, lib, root tests | `PYTHONPATH=.:lib/src $PY -m pytest -q classify/tests lib/tests tests` | nothing |
| SDLC tools | `OMNI_PYTHON=$PY bash omni-sdlc/tests/test_omni_branch.sh && OMNI_PYTHON=$PY bash omni-sdlc/tests/test_omni_merge_lane.sh` | git |
| Public hygiene | `python3 scripts/hygiene.py` | nothing |
| Commit trailers | `python3 scripts/check_trailers.py origin/main..HEAD` | the branch's history |

**Server URLs.** As `omnidev`, the testing ground's own cluster:

```bash
export ATMA_TEST_SERVER_URL="postgresql:///postgres?host=$HOME/pgdata&port=5434"
export OMNI_TEST_SERVER_URL="$ATMA_TEST_SERVER_URL"
```

In an installed checkout, `dbname=postgres` with `PGHOST=$PWD/.omni-local/socket`. In CI, the
Postgres service at `postgresql://postgres@localhost:5432/postgres`, with the password in
`PGPASSWORD`.

Run with a clean environment so nothing from the shell leaks in, for example
`env -i HOME=$HOME PATH=/usr/bin:/bin ATMA_TEST_SERVER_URL=... .venv/bin/python -m pytest -q`.

## What CI runs

`.github/workflows/ci.yml` runs every suite above on Ubuntu with Postgres 16, on every pull request
and every push to `main`. The macOS installer and the SwiftUI apps aren't covered by CI: changes to
`install.sh`, `scripts/local.py`, `scripts/bundles.py` or `mac/` need `./install.sh` plus a manual
check in the testing ground, recorded on the card.

## When a test fails

- Reproduce it alone: `pytest -q path/to/test_file.py::test_name -x`.
- A failure you didn't cause (it also fails on `main`): don't fix it in your branch. Add a card
  with the failing command and its output, and say so on your own card.
- Never skip, delete or loosen a test to get green. If a test is wrong, say why in the commit that
  changes it.
