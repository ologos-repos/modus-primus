#!/usr/bin/env bash
# Install + enable the console as a systemd user service.
# Idempotent — re-running picks up template changes.
set -euo pipefail

cd "$(dirname "$0")/.."
CONSOLE_DIR="$(pwd)"
TEMPLATE="$CONSOLE_DIR/console.service.template"
USER_UNIT_DIR="$HOME/.config/systemd/user"
USER_UNIT="$USER_UNIT_DIR/console.service"

if [ ! -f "$TEMPLATE" ]; then
    echo "FAIL: template not found: $TEMPLATE" >&2
    exit 1
fi

if [ ! -f "$CONSOLE_DIR/.env" ]; then
    echo "FAIL: $CONSOLE_DIR/.env missing — copy .env.example and edit before installing." >&2
    exit 1
fi

mkdir -p "$USER_UNIT_DIR"
# systemd rejects symlinks whose source filename doesn't match the unit name,
# so copy. Re-running this script picks up template changes.
cp "$TEMPLATE" "$USER_UNIT"
echo "→ installed $USER_UNIT (from $TEMPLATE)"

systemctl --user daemon-reload
systemctl --user enable console.service
systemctl --user restart console.service
sleep 1
systemctl --user status console.service --no-pager | head -10

echo ""
echo "→ smoke:"
curl -sf http://127.0.0.1:8080/healthz && echo "  ✓ /healthz on localhost"
