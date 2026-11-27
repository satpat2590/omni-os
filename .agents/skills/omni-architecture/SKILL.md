---
name: omni-architecture
description: Map of Omni OS components, their boundaries, data flows and where a given change belongs (core, Atma API, MCP, native apps, local installer, omnikit, classify, SDLC). Use when you need to understand how a part works or decide where new code goes.
---

# How Omni OS fits together

Read `docs/PRODUCT.md` for intent and `docs/DATA-MODEL.md` for records. This skill is the map.

## Components and what each owns

| Path | Owns | Never does |
|---|---|---|
| `core/omni_core/` | The **registry** (`registry.py`) binding jobs to harnesses; the **runner** (`runner.py`, `adapters.py`: script, hermes, opencode, pi); the **run ledger** (`ledger.py`, Postgres `core.runs`, spend caps); **launchd** plists from the registry (`launchd.py`); `status`/`plan`/`diagram`; the **development board** (`board.py`, schema `board`) | Interpret a domain's data |
| `core/bin/` | `omni-svc` (loads `~/.config/omni/*.env`), `omni-job` (what launchd runs), `omni-board` (the board CLI with env loaded) | Hold secrets |
| `atma/api/` | Atma's REST service (`main.py`, FastAPI). `utils/governance.py`: governed task creation and tag moves under a table lock. `utils/taxonomy.py`: the activity catalog. `utils/semantic.py`: offline NLP ranking and entailment. `utils/daily.py`: the daily classification pass. `utils/db.py`: the query builder over psycopg2. `utils/auth.py`: bearer tokens. `utils/verifiers.py`: evidence checks. `migrations/` + `scripts/migrate.py` | Call a paid model unless the owner configured one |
| `atma/mcp/` | An MCP server that exposes Atma to agents over HTTP to the API | Talk to the database directly |
| `mac/Desktop.swift` | One SwiftUI binary, built as two apps: **Atma.app** (capture, history, World Tree) and **Omni.app** (start/stop, domains, automations, classifier settings) | Hold business logic; every action goes through `scripts/desktop.py` |
| `scripts/local.py` | The installer (`./install.sh`): prerequisites, the private Postgres cluster in `.omni-local/`, the venvs (`api`, `base`), migrations, app bundles, the classifier schedule | Touch another checkout or system daemons |
| `scripts/desktop.py` | The apps' local RPC: one JSON request on stdin, one reply on stdout, under a file lock | Listen on a port |
| `scripts/classifier.py` | Classifier settings, the 03:00 LaunchAgent (`dev.omni.atma-classifier`), the daily run and its report | Run while Omni is stopped |
| `lib/src/omnikit/` | Shared clients: `jev` (decision models) and `providers` (OpenAI-compatible completion: HTTPS or loopback only, no redirects) | Know about any one domain |
| `classify/` | The ontology-driven "where does this belong" classifier | |
| `omni-sdlc/` | Agent branches in worktrees, the gated merge lane, and the repo audit | Move a live checkout's branch |
| `dashboard.py`, `system_page.py`, `static/`, `mindmap.py` | The base web dashboard (system page and the Atma tree graph) | |

## Two installs on one Mac

- **Installed checkout** (`./install.sh`): a private cluster at `<checkout>/.omni-local/socket`, databases
  `atma` and `omni`, apps in `~/Applications`, and per-user state in `.omni-local/`. Several
  checkouts can each have their own install, but the app bundles in `~/Applications` point at
  the last one installed.
- **The live instance** (the operator's `~/omni`): long-running services under launchd
  (`/Library/LaunchDaemons/dev.omni.*`: the Atma API on 8602, the MCP server, the dashboards), the
  machine's Postgres, and its own env file. Base code must work for both, so every
  machine-specific value is configuration.

## The main flows

1. **Capture.** In Atma.app: `desktop.py add` → `governance.create`. Over HTTP: `POST /api/tasks`
   (governed when `ATMA_GOVERNANCE=1` or when no category is given). Governance runs `taxonomy.lookup`:
   an exact catalog activity is tagged immediately; anything else is `pending`.
2. **Classification.** `scripts/classifier.py` runs `utils/daily.run` at 03:00, or on **Classify
   now**. It works through the catalog, then local NLP (`semantic.choose`, which abstains when
   unsure), then the provider when the owner enabled one, within a per-pass call budget. It never
   changes tags the owner linked by hand; every decision goes into `tasks.classification`.
3. **Completion.** `complete_task_record` writes `task_completions` with points (10 × priority,
   adjusted for recurrence, quality and lateness). The tree rolls points up the current ancestry.
4. **Automation.** `omni run JOB` (or **Run** in Omni.app) reads the registry, checks the cap,
   runs the harness, and writes `core.runs`.
5. **Development.** Cards on the board → agent branches → pull requests → CI → merge → the
   operator publishes and updates the instance (`omni-release`).

## Where does my change go?

- A new automation for one machine → that instance's `core/registry.yaml`, not base.
- A new Atma capability → `atma/api` (logic, tests, a migration if needed), then `desktop.py`
  and `mac/` if the apps expose it.
- Anything about how jobs run, cost or get scheduled → `core`.
- A client used by several domains → `lib/omnikit`.
- A rule for agents → `AGENTS.md` (short) or a skill here (detailed).
