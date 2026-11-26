# Atma

Atma is the tree at the centre of Omni: what you are working on, where it sits, and how much you
have grown there.

- **Tags** form the tree. Each tag has a parent, and every branch ends in one of four root
  categories: `physical`, `mental`, `financial`, `social`.
- **Tasks** carry tags, a priority, an optional deadline and recurrence, and a `verification` spec
  that says what evidence counts as done.
- **Completions** record a finished task with its quality and points. Points land on the task's
  tags and roll up the tree; `growth_scores_28d` is the rolling 28-day view.
- **Verifications** are Gyani's exams and submission reviews: the record that a completion was
  earned, not just claimed.

## The three parts

| Part | Runs as | What it does |
|---|---|---|
| `api/` | `uvicorn main:app --port 8602` | The REST API for tasks, tags, completions and summaries. It also does LLM auto-tagging, which fails open: a task is created even when tagging fails. Writes need a bearer token. |
| `app/` | `uvicorn server:app --port 8601` | The dashboard: growth, the Atma tree, triage (learn it yourself or delegate to an agent), and Gyani, the built-in tutor and examiner. |
| `mcp/` | `python atma_remote_server.py` | An MCP server, so agents can list, create and complete tasks through the API. |

## Database

Plain Postgres, reached through `ATMA_DATABASE_URL`. `api/migrations/000_base.sql` creates
everything; `api/scripts/migrate.py` applies migrations once each and records them in
`schema_migrations`. See [`api/migrations/README.md`](api/migrations/README.md).

The owner of the tree is user 1 (`ATMA_OWNER_ID`). Agents are users with `user_type = 'agent'`, and
the tags linked to them in `agent_domains` are what triage offers to delegate to them.

## Settings

Every setting is an environment variable. Keep them in `~/.config/omni/*.env`, with every value
quoted; `core/bin/omni-svc` loads those files for launchd jobs and services.

| Variable | Used by | Meaning |
|---|---|---|
| `ATMA_DATABASE_URL` | all | Atma's Postgres. |
| `ATMA_AGENT_TOKEN` | api | Bearer token with read and write access, acting for the owner. |
| `ATMA_READONLY_AGENT_TOKEN` | api | Bearer token with read access only. |
| `ATMA_AGENT_TOKENS_JSON` | api | More agents, each with its own token and scopes: `{"Researcher": {"token": "…", "scopes": ["read","write"]}}`. Each acts as the user of the same name. |
| `ATMA_OWNER`, `ATMA_OWNER_ID` | api, mindmap | The owner's name (default: user `ATMA_OWNER_ID`'s name) and id (default `1`). |
| `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY` | api, app | Optional LLM keys for auto-tagging, triage and Gyani. Without them those features fall back gracefully. |
| `ATMA_BASE_URL`, `ATMA_BEARER_TOKEN` | mcp | Where the MCP server reaches the API (required; for example `http://127.0.0.1:8602`), and the token it sends (the API's `ATMA_AGENT_TOKEN`). |

**Evidence sources.** These are what nightly auto-verification and the tutor's context read. Any
that are missing simply find no evidence.

| Variable | Default | Meaning |
|---|---|---|
| `ATMA_SHIP_REPOS` | `~/omni` | Git repos whose commits count as shipping (`:`-separated). |
| `ATMA_SHIP_AUTHOR` | any author | Only commits by this email count. |
| `ATMA_VAULT` | `~/Obsidian` | A notes vault (Obsidian or any folder of Markdown). |
| `ATMA_VAULT_DAILY_DIR`, `ATMA_VAULT_POETRY_DIR`, `ATMA_VAULT_ROAMINGS_DIR`, `ATMA_VAULT_CURRICULUM_DIR` | `Daily-Notes`, `Poetry`, `Roamings`, `Curriculum` | Folders inside the vault. |
| `ATMA_WHOOP_DB` | none | A SQLite export of workouts and strain. |

## Tests

```bash
cd api && ATMA_TEST_SERVER_URL="postgresql:///postgres?host=/tmp" .venv/bin/python -m pytest -q
cd app && .venv/bin/python -m pytest -q tests
```

The API's database tests create a brand-new database from the migrations on the local server you
name, and drop it afterwards. The fixture refuses any server that is not local.
