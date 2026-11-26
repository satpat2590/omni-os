# Omni SDLC

How changes land in an Omni repo, whoever writes them. Every change rides its own branch, is
written in a linked worktree (never in the live checkout services run from), and enters the repo's
base branch only through a lane that tests it first.

| Command | What it does | Changes |
|---|---|---|
| `bin/omni-sdlc audit` | Read-only hygiene report across every repo in `repos.yaml`: base branch, ahead/behind, uncommitted files, remote, stray `.git` folders. | nothing |
| `bin/omni-sdlc branch <repo> <agent> <slug> [--push]` | Creates `agent/<agent>/<slug>` off `origin/<base>` in `<repo>/.worktrees/<agent>-<slug>`. | a branch and a worktree |
| `bin/omni-sdlc merge <repo> <branch> [--dry-run]` | The merge lane. It runs the repo's `test` in a throwaway detached worktree of the branch, then makes a no-ff merge into the base and tags it. On conflict it aborts and stops: a conflict is a third party's to resolve. | a merge commit on the base |

The lane never moves a live checkout's branch. It refuses to merge unless the live checkout is
already on the base branch and clean.

## repos.yaml

One entry per repo: `path`, `remote`, `base` (the branch the lane merges into and `branch` draws
from; `main` when unset), `test` (the command the lane runs), and `test_env`. In `test_env`,
`{root}` expands to the checkout under test. A machine keeps its own `repos.yaml`; without one,
the tools use `repos.example.yaml`.

The tools run with Omni's own interpreter: `$OMNI_PYTHON`, else `core/.venv/bin/python`, else
`python3`.

## Tests

```bash
bash tests/test_omni_branch.sh && bash tests/test_omni_merge_lane.sh
```

Both build throwaway repos and a bare origin under a temporary directory, and touch no real repo.
