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
                                       └──▶ public Omni OS repo (published by the operator only)
```

1. **Testing ground (`omnidev`).** This is a separate macOS user with its own checkout of `main`,
   its own venvs and no secrets. Base changes are written and tested here. If a test passes here,
   it passes on a clean machine, not just on the operator's account. Everything shared (Homebrew,
   the system Python) is exactly what a new user would have.
2. **Shared base repo.** This is a bare repo that both users can write to (group `staff`). The
   testing ground pushes `main` here. It needs no GitHub credentials.
3. **Live instance (`omni`).** This user pulls `main` from the shared repo, runs the tests again,
   publishes `main`, and merges it into its instance branch. Only the operator account publishes.

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
uv venv --python 3.12 core/.venv && uv pip install --python core/.venv/bin/python -e "core[dev]" -e lib
(cd core && .venv/bin/python -m pytest -q)
bash omni-sdlc/tests/test_omni_branch.sh && bash omni-sdlc/tests/test_omni_merge_lane.sh
git commit -am "…" && git push origin main

# as the operator (omni)
cd ~/worktrees/omni-base && git pull --ff-only base main     # retest here, then publish
cd ~/omni && git merge main                                  # into instance/<name>; retest
```
