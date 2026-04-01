#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/workspace/.devcontainer"
LOG_FILE="$LOG_DIR/start-dev.log"
mkdir -p "$LOG_DIR"

exec >>"$LOG_FILE" 2>&1

echo "========================================"
echo "start-dev.sh invoked at $(date -Is)"
echo "========================================"

export PATH="$HOME/.cargo/bin:$PATH"

################################
# Backend
################################

echo "[backend] starting uvicorn"

cd /workspace/backend

if [ ! -d ".venv" ]; then
  echo "[backend] ERROR: backend/.venv missing"
  exit 1
fi

source .venv/bin/activate

echo "[backend] provisioning database and applying migrations"
cd /workspace
python scripts/bootstrap_db.py
cd /workspace/backend

setsid uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  > "$LOG_DIR/uvicorn.log" 2>&1 &

echo "[backend] started"

echo "start-dev.sh completed at $(date -Is)"
