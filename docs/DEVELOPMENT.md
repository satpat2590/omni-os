# Developing Omni OS

Omni OS is the base: core, Atma and the SDLC tooling. A machine that runs Omni for real adds its
own domains on top, on an instance branch. Base development happens somewhere that can't reach that
instance, and a change only moves on after its tests pass there.

## Three places, one direction

```
 testing ground                    shared base repo                   the live instance
 macOS user `omnidev`   ──push──▶  /Users/Shared/omni-os.git  ──pull──▶  user `omni`, ~/omni
 ~/omni on main                    (main)                               branch instance/<name>
                                       │
                                       └──▶ github.com/satpat2590/omni-os (published by the operator only)
```

1. **Testing ground (`omnidev`).** This is a separate macOS user with its own checkout of `main`,
   its own venvs and no secrets. Base changes are written and tested here. If a test passes here,
   it passes on a clean machine, not just on the operator's account. Everything shared (Homebrew,
   the system Python) is exactly what a new user would have.
2. **Shared base repo.** This is a bare repo that both users can write to (group `staff`). The
   testing ground pushes `main` here. It needs no GitHub credentials.
3. **Live instance (`omni`).** This user pulls `main` from the shared repo into its `public-main`
   worktree, runs the tests again, pushes it to the public repo, and merges it into its instance
   branch. Only the operator account publishes.

The public repo's history starts at its first release. The shared repo and the testing ground use
that history, and the instance branch has it merged in, so every later change is an ordinary
fast-forward or merge.

Changes flow one way: from the testing ground into `main`, and from `main` into each instance.
Nothing moves from an instance back into `main`.

## Rules that keep merges conflict-free

- **Base and an instance never edit the same path.** Base ships configs as `*.example.*`. Each
  loader takes the machine's real file when it exists:

  | Real file | Base fallback |
  |---|---|
  | `core/registry.yaml` | `core/registry.example.yaml` |
  | `core/rules/GLOBAL.md` | `core/rules/GLOBAL.example.md` |
  | `omni-sdlc/repos.yaml` | `omni-sdlc/repos.example.yaml` |
  | `classify/omni_ontology.yaml` | `classify/omni_ontology.example.yaml` |

- **Instance-only tests** go in files that base never has, for example
  `core/tests/test_instance_registry.py`.
- **A base commit that deletes instance files** is merged into the instance with `git merge -s ours`.
  The instance records that it has seen the commit and keeps its own copies.
- **No domain code on `main`.** Atma is the only domain base ships.

## Testing ground rules

- **No secrets.** `omnidev` has no `~/.config/*.env`. A test that needs a live API key must skip
  itself when the key is missing; for example, the live Jev check in `classify/tests`.
- **No production databases.** Tests mock their clients or use a local database. Atma's database
  tests run against the testing ground's own Postgres.
- **Use Omni's own interpreter.** Tools resolve `$OMNI_PYTHON`, then `core/.venv/bin/python`, then
  `python3`. Never rely on a machine-specific `python3`.
- **Its own Postgres.** The testing ground runs its own cluster, socket-only, on its own port.
  `ATMA_TEST_SERVER_URL` points the Atma tests at it, and every run builds and drops its own
  database.
- **Never install launchd jobs from the testing ground.** `/Library/LaunchDaemons` is shared by
  every user, and the base registry's labels (`dev.omni.*`) are the instance's labels too.
  `omni check` reports the collision, and `omni launchd apply` refuses to rewrite another user's
  plist.
- **Quote env values.** `~/.config/omni/*.env` files are sourced by bash, so an unquoted `&` in a
  URL silently drops the line.

## One change, start to finish

```bash
# as omnidev
cd ~/omni
OMNI_AGENT=<you> core/bin/omni-board claim <id>     # the card first (see .agents/skills/omni-change)
uv venv --python 3.12 core/.venv && uv pip install --python core/.venv/bin/python -e "core[dev]" -e lib
(cd core && .venv/bin/python -m pytest -q)
bash omni-sdlc/tests/test_omni_branch.sh && bash omni-sdlc/tests/test_omni_merge_lane.sh
git commit -am "…"       # ends with Card: OMNI-<id> and Agent: <you>
git push origin <branch>  # the operator opens the pull request; CI gates the merge

# as the operator (omni)
cd ~/worktrees/omni-base                                     # branch public-main
git pull --ff-only base main                                 # what the testing ground pushed
(cd core && .venv/bin/python -m pytest -q)                   # retest, then publish:
git push public public-main:main
cd ~/omni && git merge public-main                           # into instance/<name>; retest
```

## The agent suite: how agents develop Omni

Every coding agent (Claude Code, Codex, OpenCode, Pi) works from the same context, on the same
board, and through the same gate.

| File | Read by | What it is |
|---|---|---|
| `AGENTS.md` | Codex, OpenCode, Pi (and Claude Code through `CLAUDE.md`) | The contract: accounts, the card-to-PR loop, the hard rules |
| `.agents/skills/omni-*/SKILL.md` | Pi, OpenCode, Codex; Claude Code through `.claude/skills` | Board, change, test, review, architecture, migrations, release |
| `.opencode/` | OpenCode | `omni-dev` (the default builder) and `omni-reviewer` (read-only), with permissions that ask before pushing and refuse `git stash`, `pkill`, `launchctl` and `sudo` |
| `.claude/agents/omni-reviewer.md` | Claude Code | The same read-only reviewer |
| `scripts/omni-dev` | you | `scripts/omni-dev opencode` or `scripts/omni-dev pi ...`: starts the harness with its board identity. It refuses to start in a live instance tree, and it never loads the machine's secrets into the agent |

**The board.** `core/bin/omni-board` (`omni board` in core) is the shared list of work: cards,
atomic claims, and a history that records which agent and which account did what. Point every
account at one board with `OMNI_BOARD_URL`; without it, the board uses the ledger's database.
Create its tables once with `omni board migrate`.

**The gate.** `.github/workflows/ci.yml` runs every suite against Postgres 16, `scripts/hygiene.py`
(the base names nobody and no machine; a machine adds private patterns through
`OMNI_HYGIENE_EXTRA`), and `scripts/check_trailers.py` (every commit in a pull request carries
`Card: OMNI-<id>` and `Agent: <identity>`). Protect `main` so these checks must pass before merging.

**Headless agents.** An instance can run Pi or OpenCode as a registry job, with a spend cap and a
ledger row for every run:

```yaml
# core/registry.yaml on the instance branch
jobs:
  dev-triage:
    domain: omni
    harness: pi
    prompt: "Load the omni-board skill. List ready cards and comment on any that lack a clear definition of done."
    monthly_usd: 5
    workdir: ~/worktrees/dev-triage
```
