#!/usr/bin/env bash
set -eu

cd /app

python scripts/provision_db.py

cd /app/backend
alembic upgrade head

exec uvicorn app.main:app \
  --host "${APP_HOST}" \
  --port "${APP_PORT}" \
  --proxy-headers
