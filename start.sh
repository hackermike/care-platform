#!/usr/bin/env bash
# First-run bootstrap: venv, dependencies, migrate, serve.
# Requires Postgres — start it first with:  docker compose up -d db
set -e

if ! command -v python3 &>/dev/null; then
  echo "Python 3 is required. https://www.python.org/downloads/"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Setting up for the first time..."
  python3 -m venv .venv
  .venv/bin/pip install -r requirements-dev.txt -q
fi

# Load .env if present (DATABASE_URL, SECRET_KEY).
[ -f .env ] && set -a && . ./.env && set +a

echo "Applying migrations..."
.venv/bin/alembic upgrade head

echo "Starting Care Platform on http://localhost:8000 (Ctrl+C to stop)"
.venv/bin/uvicorn app.main:app --reload --log-level warning
