#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.hxie.io-worker-manager"
SOURCE_PLIST="$ROOT/launchd/$LABEL.plist"
TARGET_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TMP_PLIST="$(mktemp)"
trap 'rm -f "$TMP_PLIST"' EXIT

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs" "$ROOT/data"
awk -v root="$ROOT" '{ gsub(/__ROOT__/, root); print }' "$SOURCE_PLIST" > "$TMP_PLIST"
cp "$TMP_PLIST" "$TARGET_PLIST"

launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$TARGET_PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed and started $LABEL"
echo "Logs:"
echo "  $ROOT/logs/launchd.out.log"
echo "  $ROOT/logs/launchd.err.log"
