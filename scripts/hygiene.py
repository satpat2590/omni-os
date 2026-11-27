#!/usr/bin/env python3
"""Check that the public base carries nobody's secrets, contact details or home paths.

    python3 scripts/hygiene.py            # every tracked file
    python3 scripts/hygiene.py FILE ...   # just these

Exit 1 when anything is found. Patterns here are generic, so this file can be public. A machine can
add its own patterns (its owner's names, hosts, domains) in a file outside the repo, one regular
expression per line, named by OMNI_HYGIENE_EXTRA; those are checked too and never printed in full.
"""
import os
import re
import subprocess
import sys

CHECKS = {
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "API token": r"\b(sk-ant-[A-Za-z0-9_-]{16,}|sk-or-v1-[A-Za-z0-9]{16,}|sk-proj-[A-Za-z0-9_-]{16,}"
                 r"|gh[pousr]_[A-Za-z0-9]{30,}|xox[bpas]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|GOCSPX-[A-Za-z0-9_-]{10,})",
    "credentials in a URL": r"[a-z][a-z0-9+.-]*://[^\s/:@'\"]+:[^\s/@'\"$<{]{4,}@",
    "JWT": r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    "personal email": r"\b[A-Za-z0-9._%+-]+@(gmail|googlemail|yahoo|outlook|hotmail|icloud|me|proton|protonmail)\.(com|me)\b",
    "home path": r"(?<![\w$])/(Users|home)/(?!Shared/)[A-Za-z0-9._-]+/",
    "private address": r"\b(192\.168|10\.\d{1,3}|172\.(1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b",
}
SKIP = re.compile(r"(^|/)(package-lock\.json|.*\.(png|jpg|jpeg|gif|ico|onnx|lock))$")
# The hygiene check itself, and its own tests, have to name what they look for.
SELF = {"scripts/hygiene.py", "tests/test_hygiene.py"}


def tracked():
    # Tracked files plus new ones not yet committed (but not ignored ones): agents run this before committing.
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, check=True).stdout
    return [f for f in out.split("\0") if f]


def extra_patterns():
    path = os.environ.get("OMNI_HYGIENE_EXTRA")
    if not path:
        return {}
    lines = [l.strip() for l in open(os.path.expanduser(path)) if l.strip() and not l.startswith("#")]
    return {f"machine pattern {i + 1}": l for i, l in enumerate(lines)}


def scan(files, checks):
    compiled = {name: re.compile(p) for name, p in checks.items()}
    found = []
    for f in files:
        if f in SELF or SKIP.search(f) or not os.path.isfile(f):
            continue
        try:
            text = open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for name, rx in compiled.items():
                m = rx.search(line)
                if m:
                    shown = m.group(0) if not name.startswith("machine") and name not in ("API token", "JWT", "private key", "credentials in a URL") \
                        else m.group(0)[:6] + "…"
                    found.append((f, n, name, shown))
    return found


def main(argv):
    files = argv or tracked()
    found = scan(files, {**CHECKS, **extra_patterns()})
    for f, n, name, shown in found:
        print(f"{f}:{n}: {name}: {shown}")
    if found:
        print(f"\nhygiene: {len(found)} finding(s). Base must not carry secrets, contact details or "
              "machine paths: make it configuration, or use a placeholder.", file=sys.stderr)
        return 1
    print(f"hygiene: clean ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
