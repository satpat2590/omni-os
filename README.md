# Omni OS

**A personal operating system for growing yourself, on hardware you own.**

At the centre of Omni is **Atma**, a tree of everything you are working on. Each task you take on is
tagged to a place on the tree, carries points and a deadline, and when you finish it the points
land on that tag and flow up to one of four roots: **Physical, Mental, Financial, Social**. Over
time the tree shows where you have actually grown, not where you meant to.

Around Atma you build **domains**: automations for a part of your life (finance, health, research,
whatever matters to you) that help you finish the tasks on your tree. **Agents** can work inside
those domains on your behalf, and Omni keeps them honest: every run is recorded, every agent has a
spend cap, and nothing reaches your machine's live state without a gated merge.

Omni OS is the base: Atma, the runner that drives agents and jobs, and the tooling to develop it.
Your own domains live on your own branch.

> **Status: early.** Omni OS runs today on a single Mac (launchd, Postgres, Python 3.12). Linux
> support, a guided installer, and per-tag governance rules are on the roadmap below.

## What's in the box

| Directory | What it is |
|---|---|
| [`atma/`](atma/README.md) | **Atma**: the task, tag and points API (`atma/api`), its dashboard with Gyani, the built-in tutor and examiner (`atma/app`), and an MCP server so agents can read and write tasks (`atma/mcp`). |
| [`core/`](core/README.md) | **The runner.** A registry binds every job to a harness (a plain script or an agent runtime: Hermes, OpenCode, Pi); `omni run JOB` dispatches it, enforces its monthly spend cap, and writes every run to a Postgres ledger. Also `omni status`, `omni plan` and the system page. |
| [`omni-sdlc/`](omni-sdlc/README.md) | **How changes land.** Agents work on their own branch in a linked worktree; the merge lane runs the repo's tests in a throwaway checkout and merges only into the repo's base branch. |
| [`lib/`](lib/README.md) | **omnikit**: one shared client for decision models (Jev) used across Omni. |
| [`classify/`](classify/README.md) | The ontology-driven classifier that answers "where does this belong in Omni?" |
| `dashboard.py`, `system_page.py`, `mindmap.py` | The base dashboard: system status, and the Atma tree drawn nightly from your data. |

## How it fits together

```
        you ─── tasks ───▶  Atma API  ──▶  Postgres (tasks, tags, completions, verifications)
         ▲                     ▲  ▲
         │                     │  └── Atma MCP ◀── agents
   Atma dashboard              │
   (tree, Gyani)         omni run JOB ── registry ── harness (script / Hermes / OpenCode / Pi)
                                 │
                                 └── run ledger: cost, status, refusals (spend caps)
```

- **The tree grows from evidence.** A task's points land when it is completed. Nightly
  `atma-auto-verify` checks evidence for recurring tasks (commits, notes, workouts) and records the
  completion itself, and Gyani can examine you before a completion counts.
- **Agents never get a blank cheque.** Every job, agent or not, runs through `omni run`. A job is
  refused, and the refusal recorded, when it is disabled, its harness is missing, or its monthly
  cap is reached.
- **Secrets have one home.** Everything reads its keys from the environment. `core/bin/omni-svc`
  loads `~/.config/omni/*.env` for launchd jobs and services; nothing secret goes in a repo or a plist.

## Quick start

You need macOS, Python 3.12, PostgreSQL 16 or newer, and [`uv`](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/satpat2590/omni-os.git ~/omni && cd ~/omni

# 1. Secrets and settings: one file, mode 600, outside the repo. Quote every value: the file is
#    sourced by bash, so an unquoted & or ? in a URL silently drops the line.
mkdir -p ~/.config/omni && touch ~/.config/omni/omni.env && chmod 600 ~/.config/omni/omni.env
#    ATMA_DATABASE_URL="postgresql://atma:…@127.0.0.1:5432/atma"
#    OMNI_DATABASE_URL="postgresql://omni:…@127.0.0.1:5432/omni"
#    ATMA_AGENT_TOKEN="…"          # bearer token agents and the MCP server use
#    OPENROUTER_API_KEY="…"        # optional: auto-tagging and Gyani (also ANTHROPIC_API_KEY)

# 2. Atma's database, from nothing.
createdb atma && createdb omni
cd atma/api && uv venv --python 3.12 && uv pip install -r requirements-dev.txt
../../core/bin/omni-svc .venv/bin/python scripts/migrate.py
psql atma -c "insert into users (id, name) values (1, 'Me')"       # you: the owner of the tree

# 3. Run it.
../../core/bin/omni-svc .venv/bin/python -m uvicorn main:app --port 8602      # Atma API
cd ../app && uv venv --python 3.12 && uv pip install -r requirements-dev.txt
../../core/bin/omni-svc .venv/bin/python -m uvicorn server:app --port 8601   # Atma dashboard

# 4. The runner.
cd ../../core && uv venv --python 3.12 && uv pip install -e ".[dev]"
../core/bin/omni-svc .venv/bin/omni migrate && ../core/bin/omni-svc .venv/bin/omni check
```

Then open <http://127.0.0.1:8601>. `core/registry.example.yaml` lists the services and the two
nightly Atma jobs, and `sudo .venv/bin/omni launchd apply` writes their launchd plists from it.
[`atma/README.md`](atma/README.md) covers every setting.

`omni check` lists the agent harnesses it can't find (Hermes, OpenCode, Pi). They are optional:
script jobs need none of them.

## Running your own Omni

Omni OS is the base, and your Omni is a branch of it. Keep your domains, your registry and your
agents on a branch such as `instance/<you>`, and merge `main` into it whenever the base moves on.
Base never edits a path that an instance owns: configs ship as `*.example.*`, and every loader takes
your real file when it exists.

| Your file | Base fallback |
|---|---|
| `core/registry.yaml` | `core/registry.example.yaml` |
| `core/rules/GLOBAL.md` | `core/rules/GLOBAL.example.md` |
| `omni-sdlc/repos.yaml` | `omni-sdlc/repos.example.yaml` |
| `classify/omni_ontology.yaml` | `classify/omni_ontology.example.yaml` |

[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) explains how the base itself is developed: on a
separate macOS user that has no secrets and its own Postgres, so every change is proven on a clean
machine before it reaches anyone's live Omni.

## Tests

```bash
# from the repo root
(cd core && .venv/bin/python -m pytest -q)
bash omni-sdlc/tests/test_omni_branch.sh && bash omni-sdlc/tests/test_omni_merge_lane.sh
(cd atma/api && ATMA_TEST_SERVER_URL="postgresql:///postgres?host=/tmp" .venv/bin/python -m pytest -q)
(cd atma/app && .venv/bin/python -m pytest -q tests)
PYTHONPATH=.:lib/src core/.venv/bin/python -m pytest -q classify/tests lib/tests
```

Atma's database tests build a brand-new database from the migrations for every run, on a local
server you name in `ATMA_TEST_SERVER_URL`, and drop it afterwards. Without it they skip.

## Roadmap

- **Governance on tags.** A static or agentic check attached to a tag, which covers its whole
  subtree: a test, or a submission such as a photo or a document. Atma's verifications, exams and
  submissions are the first pieces of this.
- **Guiding agents.** An optional companion that reads your tree and proposes the next tasks with
  calibrated points and deadlines.
- **Odin.** Small fine-tuned decision models for fast, cheap classification, starting with tagging.
- **Install anywhere.** Generating launchd and systemd units from the registry, and Linux support.

## License

Not chosen yet. Until a license is added, all rights are reserved.
