---
name: omni-release
description: Operator-only steps to open a base pull request on GitHub, publish merged base to the public repo, and bring an instance up to date safely. Use only as the operator account (omni), when a card in review needs a pull request, or after a base merge.
---

# Releasing base and updating the instance

Only the operator account (`omni`) publishes. Agents in `omnidev` stop at "pushed to the shared
base repo, card in review".

## Remotes and branches (operator)

| Name | What |
|---|---|
| `base` | `/Users/Shared/omni-os.git`: the shared repo that omnidev pushes to |
| `public` | `github.com/satpat2590/omni-os`: the published base |
| `public-main` | The worktree `~/worktrees/omni-base`, tracking `public/main` |
| `instance/<name>` | The live instance, in `~/omni` (services run from it) |

## 1. Open the pull request for a branch in review

```bash
cd ~/worktrees/omni-base
git fetch base && git push public base/<branch>:refs/heads/<branch>
gh pr create --repo satpat2590/omni-os --head <branch> --title "<card title>" \
  --body "Card: OMNI-<id>. <what changed, why, what was verified>"
OMNI_AGENT=human core/bin/omni-board link <id> --pr <url>
```

CI runs on the pull request. It must be green before anyone merges.

## 2. After the merge: sync the shared repo

```bash
git fetch public && git checkout public-main && git merge --ff-only public/main
git push base public-main:main
```

## 3. Bring the instance up to date

Never merge into `~/omni` blind. Services run from it.

```bash
cd ~/omni
git fetch public
git diff --stat HEAD public/main                 # what will change
git diff --name-only --diff-filter=D HEAD...public/main   # what base deletes
```

1. **Deletions.** If base deletes files the instance still uses (its own services, specs or
   tools), merge, then restore exactly those from the pre-merge commit
   (`git checkout <pre> -- <paths>`) and commit "instance: keep ...".
2. **New settings.** Base defaults are neutral. Set the instance's real values in its env file
   before restarting anything.
3. **Migrations.** Back up the database first (`pg_dump -Fc`, and verify the dump restores), then
   run the Atma and core migrations.
4. **Restart only the services whose code changed** (`sudo launchctl kickstart -k
   system/<label>`), then check their routes and `omni check`.
5. **Run the instance's own tests** (`core/tests/test_instance_registry.py` and the suites).

Record what you did on the card.
