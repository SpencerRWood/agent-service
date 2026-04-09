#!/usr/bin/env bash
set -eu

if [ "$#" -lt 4 ]; then
  echo "Usage: $0 <repo_root> <server_base_url> <target_id> <worker_token> [worker_id]"
  exit 1
fi

REPO_ROOT="$1"
SERVER_BASE_URL="$2"
TARGET_ID="$3"
WORKER_TOKEN="$4"
WORKER_ID="${5:-${TARGET_ID}-worker}"

PLIST_TEMPLATE="$REPO_ROOT/deploy/macos/com.woodhost.agent-worker.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.woodhost.agent-worker.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$REPO_ROOT/.worker"

sed \
  -e "s|__REPO_ROOT__|$REPO_ROOT|g" \
  -e "s|https://agents.woodhost.cloud|$SERVER_BASE_URL|g" \
  -e "s|mbp-primary|$TARGET_ID|g" \
  -e "s|mbp-primary-worker|$WORKER_ID|g" \
  -e "s|__WORKER_TOKEN__|$WORKER_TOKEN|g" \
  "$PLIST_TEMPLATE" > "$PLIST_DEST"

launchctl unload "$PLIST_DEST" >/dev/null 2>&1 || true
launchctl load "$PLIST_DEST"
launchctl kickstart -k "gui/$(id -u)/com.woodhost.agent-worker"

echo "Installed launchd job at $PLIST_DEST"
echo "Check status with: launchctl print gui/$(id -u)/com.woodhost.agent-worker"
