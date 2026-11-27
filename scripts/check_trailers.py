#!/usr/bin/env python3
"""Every commit names the card it serves and the agent that wrote it.

    python3 scripts/check_trailers.py origin/main..HEAD

Each non-merge commit in the range must carry, anywhere in its message:

    Card: OMNI-<number>
    Agent: <identity>          e.g. claude-code, codex, opencode/omni-dev, pi, human

This is how work from different agents stays traceable instead of mixing in one history. Merge
commits are exempt: they carry no change of their own.
"""
import re
import subprocess
import sys

CARD = re.compile(r"(?m)^Card:\s*OMNI-\d+\s*$")
AGENT = re.compile(r"(?m)^Agent:\s*[a-z0-9][a-z0-9._/-]{0,59}\s*$")


def commits(rev_range):
    out = subprocess.run(["git", "log", "--format=%H%x00%P%x00%s%x00%B%x1e", rev_range],
                         capture_output=True, text=True, check=True).stdout
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, parents, subject, body = record.split("\x00", 3)
        yield sha, parents.split(), subject, body


def main(argv):
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    bad, checked = [], 0
    for sha, parents, subject, body in commits(argv[0]):
        if len(parents) > 1:
            continue
        checked += 1
        missing = [name for name, rx in (("Card", CARD), ("Agent", AGENT)) if not rx.search(body)]
        if missing:
            bad.append((sha[:9], subject, missing))
    for sha, subject, missing in bad:
        print(f"{sha} {subject}\n    missing: {', '.join(missing)} trailer")
    if bad:
        print(f"\ncheck_trailers: {len(bad)} of {checked} commit(s) lack trailers. End each commit message with\n"
              "    Card: OMNI-<id>\n    Agent: <OMNI_AGENT>\n(see .agents/skills/omni-change)", file=sys.stderr)
        return 1
    print(f"check_trailers: {checked} commit(s), all traceable")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
