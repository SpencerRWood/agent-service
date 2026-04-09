#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/workspace/.devcontainer"
LOG_FILE="$LOG_DIR/start-dev.log"
UVICORN_LOG_FILE="$LOG_DIR/uvicorn.log"
PROMTAIL_LOG_FILE="$LOG_DIR/promtail.log"
PROMTAIL_PID_FILE="$LOG_DIR/promtail.pid"
UVICORN_PID_FILE="$LOG_DIR/uvicorn.pid"
mkdir -p "$LOG_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "========================================"
echo "start-dev.sh invoked at $(date -Is)"
echo "========================================"

export PATH="$HOME/.cargo/bin:$PATH"

if [ -n "${LOKI_PUSH_URL:-}" ]; then
  if [ -f "$PROMTAIL_PID_FILE" ] && kill -0 "$(cat "$PROMTAIL_PID_FILE")" 2>/dev/null; then
    echo "[promtail] already running"
  else
    echo "[promtail] starting"
    nohup "$HOME/.local/bin/promtail" \
      -config.file /workspace/.devcontainer/promtail-config.yml \
      -config.expand-env=true \
      >>"$PROMTAIL_LOG_FILE" 2>&1 &
    echo $! > "$PROMTAIL_PID_FILE"
    echo "[promtail] started"
  fi
else
  echo "[promtail] skipped because LOKI_PUSH_URL is not set"
fi

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

if [ -f "$UVICORN_PID_FILE" ] && kill -0 "$(cat "$UVICORN_PID_FILE")" 2>/dev/null; then
  echo "[backend] uvicorn already running"
else
  : > "$UVICORN_LOG_FILE"
  nohup bash -lc '
    cd /workspace/backend
    source .venv/bin/activate
    stdbuf -oL -eL uvicorn app.main:app \
      --host 0.0.0.0 \
      --port 8000 \
      --reload 2>&1 | tee -a /workspace/.devcontainer/uvicorn.log
  ' >/proc/1/fd/1 2>/proc/1/fd/2 &
  echo $! > "$UVICORN_PID_FILE"
fi

echo "[backend] started"

echo "start-dev.sh completed at $(date -Is)"
