@AGENTS.md

## Claude Code specifics

- Your board identity is `OMNI_AGENT=claude-code`. Use it on every `core/bin/omni-board` write and
  in the `Agent:` commit trailer.
- The skills in `.agents/skills/` are linked into `.claude/skills/`, so `omni-board`,
  `omni-change`, `omni-test`, `omni-review`, `omni-architecture`, `omni-migrations` and
  `omni-release` are available by name.
- For an independent review, use the `omni-reviewer` subagent (`.claude/agents/omni-reviewer.md`).
  It reads and runs checks; it never edits.
