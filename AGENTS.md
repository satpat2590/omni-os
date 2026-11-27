# Omni OS: instructions for coding agents

This file is the contract for every agent that changes this repository: Claude Code, Codex,
OpenCode, Pi, or anything else. `CLAUDE.md` imports it. Read it before changing anything.

Omni OS is a personal growth platform that runs on the owner's Mac. **Atma** (`atma/`) is its one
built-in domain: a tree of tags, tasks with points, completions, and governed classification.
**Core** (`core/`) is the platform: the job registry, the runner, the run ledger, and the
development board. The full map is in `.agents/skills/omni-architecture/SKILL.md`.

## Where you are decides what you may do

Run `whoami` first.

| Account | What it is | What you do here |
|---|---|---|
| `omnidev` | The testing ground. Has no secrets and its own Postgres. | All **base** work: anything that ships in the public repo. |
| `omni` | The live instance: the owner's real Omni, with domains and secrets. | **Instance** work only, and only in a worktree, never in `~/omni` itself (services run from it). |
| anything else | A fresh install or a contributor's machine. | Base work, through a fork or pull request. |

Base is everything on `main` of `github.com/satpat2590/omni-os`. An instance is a branch such as
`instance/<name>` that adds one machine's domains, registry and configuration.

## The loop: card, branch, test, commit, pull request

Nothing is built outside this loop. Two agents never work on the same thing at once, and every
commit can be traced to the card and the agent behind it.

1. **Find or create the card.** `OMNI_AGENT=<you> core/bin/omni-board list`. If no card covers
   your work, `add` one. Don't do work that has no card.
2. **Claim it.** `omni-board claim <id>`. If it's held by someone else, stop and coordinate on the
   card with `comment`. Never fork their work.
3. **Branch in a worktree.** Branch name: `agent/<agent>/omni-<id>-<slug>`, from the current
   `main` (base) or the instance branch (instance). Use `omni-sdlc/bin/omni-sdlc branch`, or
   `git worktree add`. Then `omni-board link <id> --branch <name>`.
4. **Change only what the card covers.** If you notice other work, `add` a card for it, and
   leave it.
5. **Test.** Run the suites for everything you touched (`.agents/skills/omni-test`). Paste the
   result into the card with `comment`.
6. **Commit with trailers.** Every commit message ends with:
   ```
   Card: OMNI-<id>
   Agent: <the same value as OMNI_AGENT>
   ```
   CI rejects commits without them. Keep your tool's own trailer (Co-Authored-By) as well.
7. **Push and open the pull request.** Push the branch to the shared base repo (as `omnidev`) or
   to origin (elsewhere). Then `omni-board move <id> review` and link the PR with `--pr`. On the
   Mac, the operator account opens base pull requests on GitHub.
8. **Done means merged.** The card moves to `done` after the pull request merges with CI green.
   Release a card you stop working on (`omni-board release <id> --note ...`); don't leave it
   claimed.

`OMNI_AGENT` names you on the board and in trailers: `claude-code`, `codex`, `opencode/omni-dev`,
`pi`, or `human`. Use it consistently.

## Hard rules

These come from real incidents in this repository.

- **Base never names a person or a machine.** No personal names, emails, home paths, hostnames,
  agent personas or domain names in base. Everything machine-specific is configuration: an env
  var with a neutral default, or a `*.example.*` file. `scripts/hygiene.py` checks this, and CI
  runs it.
- **Base and an instance never edit the same path.** Base ships `core/registry.example.yaml`; an
  instance has `core/registry.yaml`. Instance-only tests and docs go in files that base doesn't
  have.
- **Secrets live only in `~/.config/omni/*.env`** (or the instance's own env file), loaded by
  `core/bin/omni-svc`. Never print, copy, commit or log them. Never parse a URL that holds a
  password in a way that could echo it.
- **Migrations are append-only.** Never edit a migration that may have run somewhere. Add the next
  number. Each one must apply to an empty database and to an existing one; the tests build every
  database from the migrations.
- **Never touch the live tree or the live services.** On `omni`, work in a worktree. Never run
  `omni launchd apply` or `launchctl` as `omnidev`. Never stop processes by pattern
  (`pkill -f`, `killall`); kill only PIDs you started.
- **Never `git stash`, never force-push a shared branch, never rewrite published history.**
- **Money and production data need the owner.** No trades, transfers, or production database
  writes outside the code path a card asks for.
- **Say what you verified.** Report what you ran and what it printed. Label anything you did not
  run as unverified.

## Testing

`.agents/skills/omni-test/SKILL.md` has every suite and the environment each one needs. In
short: the Atma API and the board need a **local** Postgres (`ATMA_TEST_SERVER_URL`,
`OMNI_TEST_SERVER_URL`), and they build and drop their own databases. In an installed checkout,
`./install.sh test` runs everything. CI runs the same suites on every pull request.

## Skills

| Skill | Use it when |
|---|---|
| `omni-board` | Reading or updating the board: finding work, claiming, handing off. |
| `omni-change` | Making any change, start to finish. |
| `omni-test` | Choosing and running the right tests. |
| `omni-review` | Reviewing a branch or a pull request, yours or someone else's. |
| `omni-architecture` | You need to know how a part works, or where something belongs. |
| `omni-migrations` | You're changing a database schema. |
| `omni-release` | You're the operator, publishing base or updating the instance. |

## This machine

If `docs/INSTANCE.md` exists, read it. It's the instance's own notes (its domains, services and
what is frozen), and it is never part of base.
