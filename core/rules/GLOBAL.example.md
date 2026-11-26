# Omni global rules

These apply to every agent run on this machine, in every harness. A domain's own AGENTS.md adds
to them, and wins wherever it is stricter. A machine replaces this file with its own
`rules/GLOBAL.md` on its instance branch.

1. **Secrets.** Keys live in `~/.config/*.env` and are loaded by `omni-svc`. Never print, copy or
   commit them.
2. **Databases.** Production databases are read-only unless this job's own instructions say it
   writes. Tests never touch a production database.
3. **Money.** Never place, cancel or change a live trade, or move funds, without the owner's
   explicit approval for that specific action.
4. **Code.** Work on a branch or in a git worktree. Never `git stash`, and never commit someone
   else's uncommitted work. A code task is done only when a commit exists and its tests have
   run: quote the test output.
5. **Scope.** Do the job you were given. If it needs a decision from the owner, stop and say so
   instead of guessing.
6. **Reporting.** Say what you did, what you verified and what failed. Label anything you did
   not verify as unverified.
