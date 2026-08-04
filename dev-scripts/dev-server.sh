#!/usr/bin/env bash
# Restart the dev server in the background and wait until it's healthy.
set -euo pipefail
cd "$(dirname "$0")/.."

pkill -f "uvicorn app.main:app" 2>/dev/null || true
LOG=/tmp/care-server.log
.venv/bin/uvicorn app.main:app --reload --log-level warning >"$LOG" 2>&1 &
PID=$!

for _ in $(seq 1 40); do
  if curl -sf http://localhost:8000/healthz >/dev/null 2>&1; then
    echo "Dev server ready on http://localhost:8000 (pid $PID, log $LOG)"
    exit 0
  fi
  sleep 0.25
done

echo "Dev server did not become healthy; see $LOG" >&2
exit 1
