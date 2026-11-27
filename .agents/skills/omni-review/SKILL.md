---
name: omni-review
description: Review an Omni OS branch or pull request for correctness, base hygiene, migrations, secrets and workflow compliance, and report findings ranked by severity. Use when asked to review, before moving your own card to review, and before an operator publishes.
---

# Reviewing an Omni change

Review against the card. A change that does something the card didn't ask for is a finding, even
if the code is good.

## 1. Gather

```bash
core/bin/omni-board show <id>                      # what was asked, and what was claimed
git log --format='%h %s%n%b' origin/main..<branch>    # what was done, and by whom
git diff --stat origin/main...<branch>
git diff origin/main...<branch>
```

## 2. Mechanical checks (run them; don't eyeball)

```bash
python3 scripts/hygiene.py                          # base names nobody and no machine
python3 scripts/check_trailers.py origin/main..<branch>   # every commit names its card and agent
```

Then run the test suites for every component the diff touches (`omni-test`).

## 3. Read for these, in order

1. **Correctness.** Does it do what the card says, for empty, first-run and existing data? Pay
   attention to off-by-one errors, error paths, None and NULL handling, timezones, concurrent
   writers, and retries applying twice.
2. **Data safety.** Migrations follow `omni-migrations`: append-only, apply to an empty database
   and to an existing one, no personal or domain values. A write path that could destroy data
   without the owner asking is critical.
3. **Secrets and isolation.** No key in code, a log, an error message or a test fixture. Network
   calls go only where configured. Local services bind to loopback.
4. **Base and instance separation.** Base doesn't hardcode an owner id, a person, a path or a
   domain (the owner is `ATMA_OWNER_ID`). It never edits an instance-owned path (`registry.yaml`,
   `rules/GLOBAL.md`, `repos.yaml`, `omni_ontology.yaml`, `docs/INSTANCE.md`).
5. **Tests.** New behaviour has a test that would fail without it. Nothing was skipped or loosened
   to pass.
6. **Scope and size.** One card's worth. Unrelated refactors are a finding ("split into OMNI-…").

## 4. Report

Rank the findings: **critical** (data loss, a secret, a security hole, a broken install),
**important** (wrong behaviour, a missing test, a hygiene breach), **minor**. Each finding gives
the file and line, what goes wrong in a concrete case, and the fix. Put the report on the card:

```bash
core/bin/omni-board comment <id> "$(cat review.md)"
```

If there are critical or important findings, the card goes back to the holder (`blocked`, with
the note "changes requested"). Don't fix someone else's branch yourself unless the card's holder
asks you to.
