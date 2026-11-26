#!/bin/bash
# Make omnikit importable by an Omni runtime via a .pth file in its site-packages.
# A .pth (not pip -e) needs no network and no setuptools in the target env, and points
# at src/ only, so omnikit's own tests/ can never shadow another repo's `tests` package.
# Idempotent; re-run after adding a runtime.
#
#   lib/install.sh [PYTHON ...]     default: Omni's own core/.venv/bin/python
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)/src"
OMNI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -gt 0 ]; then RUNTIMES=("$@"); else RUNTIMES=("$OMNI_ROOT/core/.venv/bin/python"); fi
for py in "${RUNTIMES[@]}"; do
    if [ ! -x "$py" ]; then echo "skip (missing): $py"; continue; fi
    sp="$("$py" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    echo "$SRC" > "$sp/omnikit.pth"
    "$py" -c 'import omnikit.jev, sys; print("ok", sys.executable, omnikit.jev.__file__)'
done
