---
name: omni-change
description: The end-to-end workflow for any change to Omni OS or an Omni instance, from card to merged pull request. Use whenever you're about to edit code, configuration, migrations or docs in an Omni repository.
---

# Making a change to Omni

## 1. Know where you are

```bash
whoami                     # omnidev = base work; omni = instance work (in a worktree only)
git -C . rev-parse --show-toplevel && git branch --show-current
```

- **Base** (anything that ships publicly) is done as `omnidev`, from `main` of the shared base repo
  (`/Users/Shared/omni-os.git`, remote `origin` in omnidev's checkouts).
- **Instance** work is done as the operator, branched from `instance/<name>`, in a worktree such as
  `~/worktrees/<card>`. Never edit `~/omni` itself: launchd services run from it.

## 2. Card and branch

```bash
export OMNI_AGENT=<you>
core/bin/omni-board claim <id>
git fetch origin
git worktree add -b agent/$OMNI_AGENT/omni-<id>-<slug> ../omni-<id> origin/main
core/bin/omni-board link <id> --branch agent/$OMNI_AGENT/omni-<id>-<slug>
```

(Use `omni-sdlc/bin/omni-sdlc branch <repo> <agent> <slug>` where the repo is in `repos.yaml`;
it does the same and places the worktree under `<repo>/.worktrees/`.)

## 3. Change

- Read the code you're changing and the tests that cover it first.
- Stay inside the card. Anything else you'd like to fix becomes a new card.
- Keep base free of anything personal. Run `python3 scripts/hygiene.py` before committing.
- A schema change follows the `omni-migrations` skill.
- Configuration is an env var with a neutral default, documented in the component's README. It is
  never a constant with someone's value in it.

## 4. Test

Use the `omni-test` skill. Run at least the suites for every component you touched, and the full
set before asking for review. Put the counts on the card:

```bash
core/bin/omni-board comment <id> "core 138 passed; atma/api 105 passed; sdlc ALL PASSED"
```

## 5. Commit

One logical change per commit. Write a subject line that says what changed, then a body that says
why and what you verified. End every commit with:

```
Card: OMNI-<id>
Agent: <OMNI_AGENT>
```

Your tool may add its own trailer (`Co-Authored-By: ...`) as well; keep it. CI fails any commit in
a pull request that lacks `Card:` or `Agent:`. `python3 scripts/check_trailers.py origin/main..HEAD`
checks this locally.

## 6. Push, pull request, review

```bash
git push -u origin agent/$OMNI_AGENT/omni-<id>-<slug>
core/bin/omni-board move <id> review --note "pushed; ready for a PR"
```

As `omnidev` you have no GitHub credentials, by design. The operator account pushes the branch to
`github.com/satpat2590/omni-os` and opens the pull request (see `omni-release`). Elsewhere,
`gh pr create` it yourself. Link it: `omni-board link <id> --pr <url>`.

CI must be green. Another agent, or the owner, reviews with the `omni-review` skill. Fix the
findings on the same branch, with the same card.

## 7. After the merge

`omni-board move <id> done`. Delete the worktree (`git worktree remove ../omni-<id>`) once it's
merged and clean.
