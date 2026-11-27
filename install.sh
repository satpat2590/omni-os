#!/bin/sh
set -eu
command -v python3 >/dev/null || { echo "Install Python 3 and rerun ./install.sh" >&2; exit 1; }
exec python3 "$(dirname "$0")/scripts/local.py" "$@"
