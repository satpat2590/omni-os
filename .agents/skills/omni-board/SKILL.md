---
name: omni-board
description: Use the shared Omni development board to find work, claim a card, record progress, hand off, or file a new card. Use before starting any Omni change, when you finish or pause one, and whenever you find work outside your card.
---

# The Omni development board

One board is shared by every agent and every account on the machine. It's how Claude Code, Codex,
OpenCode, Pi and the owner avoid building the same thing twice, or building something nobody asked
for.

Run it through `core/bin/omni-board`, which loads the board's address (`OMNI_BOARD_URL`) the same
way services load their secrets. Set `OMNI_AGENT` on every write. Add `--json` to any command when
you need to read the result.

```bash
export OMNI_AGENT=codex            # or claude-code, opencode/omni-dev, pi, human

core/bin/omni-board list                         # open cards, most urgent first
core/bin/omni-board list --mine                  # what you hold
core/bin/omni-board show 12                      # one card and its full history
core/bin/omni-board add "Short imperative title" --body-file notes.md --scope base --priority 2
core/bin/omni-board claim 12 --branch agent/codex/omni-12-fix-categories
core/bin/omni-board comment 12 "core: 138 passed; api: 105 passed"
core/bin/omni-board link 12 --pr https://github.com/satpat2590/omni-os/pull/7
core/bin/omni-board move 12 review
core/bin/omni-board release 12 --note "stopping: blocked on a decision, see comment"
```

## What the statuses mean

| Status | Meaning | Who moves it there |
|---|---|---|
| `backlog` | Known work, not ready to start. | Anyone adding a card. |
| `ready` | Clear enough that an agent can pick it up. | Whoever refines the card. |
| `in_progress` | Claimed. **Exactly one agent holds it.** | `claim` does this. |
| `review` | A pull request is open. | The holder, after pushing. |
| `blocked` | Waiting on a decision or another card. Say which in a comment. | The holder. |
| `done` | Merged, with CI green. | The holder or the owner, after the merge. |
| `dropped` | Not going to happen. Say why. | The owner. |

Moving a card to `backlog`, `ready`, `done` or `dropped` releases the claim.

## Rules

- **Claim before you write code.** If `claim` says the card is held by another agent, don't start
  a parallel version. Comment on the card, or pick another one.
- **Only the holder moves a card.** `--force` exists for the owner and for stale claims. It's
  recorded against you, so say why in `--note`.
- **One card, one branch, one pull request.** If the work splits, add cards and link them in
  comments (`see OMNI-14`).
- **Write the result on the card.** Test output, the decision you need, or why you stopped.
  The next agent reads the card, not your chat history.
- **New findings become cards.** A bug you noticed, a refactor you'd like, a review comment
  outside the change: `add` it with enough context that someone else can start, and don't do it in
  your current branch.
- **Scope.** `base` is work for the public repo (done as `omnidev`). `instance` is work on one
  machine's instance branch (done as the operator, in a worktree).

## Writing a good card

The title is an imperative under 70 characters ("Restrict tasks.category to the four roots").
The body says what's wrong or wanted, where it is (paths and lines), what done looks like, and how
to verify it. Priority runs from 1 (now) to 5 (someday); most cards are 3.
