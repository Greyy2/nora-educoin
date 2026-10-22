#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="/home/vmc03/.venvs/nora312/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

export PYTHONUNBUFFERED=1

"$PYTHON_BIN" "$SCRIPT_DIR/check_all.py" "$@"
