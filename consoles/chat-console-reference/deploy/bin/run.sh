#!/usr/bin/env bash
# Dev runner for the console.
# Usage: bin/run.sh [--port 8080]
set -euo pipefail

cd "$(dirname "$0")/.."

# Load .env if present (don't fail if missing — defaults work for chunk-2 stub)
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

exec python3 app.py "$@"
