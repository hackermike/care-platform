#!/usr/bin/env bash
# End-to-end smoke test against a real running server.
#
# Covers what the pytest suite cannot: that migrations apply to an empty
# database, that startup wiring works, that the admin CLI provisions usable
# accounts, and that a browser-shaped login round-trip actually succeeds.
#
# Uses a throwaway SQLite database so it needs no Postgres. Run it after
# changing migrations, startup, or the auth flow:
#
#     ./dev-scripts/smoke-e2e.sh
set -euo pipefail
cd "$(dirname "$0")/.."

WORK="$(mktemp -d)"
export DATABASE_URL="sqlite:///${WORK}/verify.db"
export APP_ENV=dev
export DEV_DEFAULT_TENANT_SLUG=demo

echo "==> migrate a fresh database"
.venv/bin/alembic upgrade head

echo "==> create tenant + users"
.venv/bin/python dev-scripts/manage.py create-tenant \
  --name "Riverside Counseling" --slug demo --brand-name "Riverside" \
  --support-email help@riverside.example
.venv/bin/python dev-scripts/manage.py create-user \
  --tenant demo --email dr@example.com --role therapist \
  --full-name "Dr Alex Reed" --password "correct-horse-battery"
.venv/bin/python dev-scripts/manage.py create-user \
  --tenant demo --email admin@example.com --role admin \
  --password "correct-horse-battery"

echo "==> list users"
.venv/bin/python dev-scripts/manage.py list-users --tenant demo

echo "==> start server"
.venv/bin/uvicorn app.main:app --port 8099 --log-level warning &
SERVER=$!
trap 'kill ${SERVER} 2>/dev/null || true' EXIT
sleep 4

echo "==> healthz"
curl -sS -o /dev/null -w 'health: %{http_code}\n' http://127.0.0.1:8099/healthz

echo "==> login page carries the tenant brand"
curl -sS -c "${WORK}/jar" http://127.0.0.1:8099/login | grep -o 'Riverside' | head -1

echo "==> sign in"
TOKEN="$(curl -sS -b "${WORK}/jar" -c "${WORK}/jar" http://127.0.0.1:8099/login \
  | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')"
curl -sS -b "${WORK}/jar" -c "${WORK}/jar" -o /dev/null -w 'login: %{http_code} -> %{redirect_url}\n' \
  -d "email=dr@example.com&password=correct-horse-battery&csrf_token=${TOKEN}" \
  http://127.0.0.1:8099/login

echo "==> therapist surface"
curl -sS -b "${WORK}/jar" -o /dev/null -w 'app: %{http_code}\n' http://127.0.0.1:8099/app
echo "==> admin surface is refused to a therapist"
curl -sS -b "${WORK}/jar" -o /dev/null -w 'admin: %{http_code}\n' http://127.0.0.1:8099/admin

echo "==> audit trail"
.venv/bin/python -c "
import os
from app.database import SessionLocal
from app.models.audit import AuditLog
db = SessionLocal()
for row in db.query(AuditLog).order_by(AuditLog.id).all():
    print(f'  {row.action:<28} user={row.user_id} ip={row.ip_address}')
"

echo "OK"
