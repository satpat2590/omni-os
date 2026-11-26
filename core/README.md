# Omni core

The part of Omni that stays the same whichever agent harness is in fashion: a registry of jobs, a
runner that dispatches each job to its harness, and a ledger of what every run did and cost.

```
launchd / you  ──▶  omni run JOB  ──▶  registry  ──▶  adapter  ──▶  script | Hermes | OpenCode | Pi
                                          │                                │
                                     budget check                    ledger (Postgres)
```

## Commands

Install with `uv venv --python 3.12 && uv pip install -e ".[dev]"`, then run `.venv/bin/omni`
through `bin/omni-svc`, so it has `OMNI_DATABASE_URL` and the job's secrets.

| Command | What it does |
|---|---|
| `omni list` | Every job with its harness, model and monthly cap. |
| `omni check` | Validates the registry, harness binaries, workdirs, launchd plists, global rules and the ledger; exits 1 on any problem. |
| `omni status` | Every service (launchd state and port) and how each job is fired; exits 1 if a service is down. |
| `omni plan [NAME]` | Each plan's stages and what every job in them last did. |
| `omni run JOB [--dry-run]` | Runs one job; the exit code is the job's own (64 refused, 124 timeout, 75 ledger down). |
| `omni spend --days N` | Runs, failures, unknown-cost runs and spend per job. |
| `omni launchd diff\|apply [JOB...]` | Shows or writes the launchd plists the registry implies (`apply` uses `sudo`). |
| `omni diagram [--write]` | Mermaid for the system and every plan. |
| `omni migrate` | Creates or updates the ledger tables. |

## The registry

`registry.yaml` is this machine's registry. Without one, core uses `registry.example.yaml`, the
base: the platform and Atma. Each job has a `domain`, a `harness`, and either a `command` (script
jobs) or a `prompt`/`prompt_file` (agent jobs). Optional fields are `model`, `profile`, `agent`,
`tools`, `timeout_s`, `monthly_usd`, `enabled`, `rules`, `schedule`, `launchd`, `log` and `workdir`.
Unknown keys are errors.

`services` lists the long-running processes launchd keeps alive; `omni status` watches them, and
the runner never starts them. `plans` group jobs into stages for `omni plan` and the system page.

## What the runner guarantees

- Every run, and every refusal, leaves a row in the ledger.
- A job is refused, with the reason recorded, when it is disabled, its harness isn't installed, its
  workdir is missing, or its `monthly_usd` cap is reached. A cap also refuses a job when earlier
  runs this month have unknown cost, so an unpriced harness can't spend without limit.
- Agent prompts are prefixed with `rules/GLOBAL.md`, or `rules/GLOBAL.example.md` in base: the
  rules every agent on the machine follows.
- `bin/omni-job` is what launchd runs. If Omni itself cannot start, it runs a script job's own
  command directly, so a broken platform never stops a feed. Agent jobs have no such fallback.
- `omni launchd apply` never rewrites a plist that runs as another user. On a machine with two
  Omni installs (an instance and a testing ground), give each registry its own labels.

## Tests

```bash
.venv/bin/python -m pytest -q
```
