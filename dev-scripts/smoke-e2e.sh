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

echo "==> therapist profile, licence, and a client"
.venv/bin/python -c "
from app.database import SessionLocal
from app.models.client import Client
from app.models.provider import TherapistLicense, TherapistProfile
from app.models.user import User
db = SessionLocal()
user = db.query(User).filter(User.email == 'dr@example.com').one()
profile = TherapistProfile(tenant_id=user.tenant_id, user_id=user.id, name='Dr Alex Reed',
                           credentials='LCSW', npi='1234567890', practice_name='Riverside')
db.add(profile); db.flush()
db.add(TherapistLicense(tenant_id=user.tenant_id, therapist_id=profile.id, state='CA'))
db.add(Client(tenant_id=user.tenant_id, therapist_id=profile.id, first_name='Sam',
              last_name='Rivera', state='CA', diagnosis_codes='F41.1'))
db.commit()
print('  seeded therapist profile, CA licence, and one client')
"

echo "==> caseload"
curl -sS -b "${WORK}/jar" http://127.0.0.1:8099/app/clients | grep -o 'Sam Rivera' | head -1

echo "==> book a session"
CT="$(curl -sS -b "${WORK}/jar" -c "${WORK}/jar" http://127.0.0.1:8099/app/clients \
  | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')"
curl -sS -b "${WORK}/jar" -o /dev/null -w 'book: %{http_code}\n' \
  -d "starts_at=2026-03-02T15:00&cpt_code=90837&csrf_token=${CT}" \
  http://127.0.0.1:8099/app/clients/1/appointments

echo "==> superbill PDF"
curl -sS -b "${WORK}/jar" -o "${WORK}/superbill.pdf" -w 'superbill: %{http_code} %{content_type}\n' \
  "http://127.0.0.1:8099/app/clients/1/superbill?start=2026-01-01&end=2026-12-31"
head -c 4 "${WORK}/superbill.pdf"; echo " <- PDF magic bytes"

echo "==> client portal: seed a portal login and a consent form"
cat > "${WORK}/consent.txt" <<'CONSENT'
I consent to receive psychotherapy services from this practice.
CONSENT
cat > "${WORK}/intake.json" <<'SCHEMA'
[{"key": "goals", "label": "What brings you in?", "type": "textarea", "required": true}]
SCHEMA
.venv/bin/python dev-scripts/manage.py create-user \
  --tenant demo --email sam@example.com --role client \
  --full-name "Sam Rivera" --password "correct-horse-battery"
.venv/bin/python dev-scripts/manage.py link-client \
  --tenant demo --email sam@example.com --client-id 1
.venv/bin/python dev-scripts/manage.py add-form-template \
  --tenant demo --name "Consent to treatment" --kind consent \
  --body-file "${WORK}/consent.txt" --schema-file "${WORK}/intake.json" \
  --requires-signature

echo "==> therapist assigns the form"
CT2="$(curl -sS -b "${WORK}/jar" -c "${WORK}/jar" http://127.0.0.1:8099/app/clients/1 \
  | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')"
curl -sS -b "${WORK}/jar" -o /dev/null -w 'assign: %{http_code}\n' \
  -d "template_id=1&csrf_token=${CT2}" http://127.0.0.1:8099/app/clients/1/forms

echo "==> client signs in and signs the consent"
curl -sS -c "${WORK}/cjar" http://127.0.0.1:8099/login > /dev/null
CT3="$(curl -sS -b "${WORK}/cjar" -c "${WORK}/cjar" http://127.0.0.1:8099/login \
  | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')"
curl -sS -b "${WORK}/cjar" -c "${WORK}/cjar" -o /dev/null -w 'client login: %{http_code}\n' \
  -d "email=sam@example.com&password=correct-horse-battery&csrf_token=${CT3}" \
  http://127.0.0.1:8099/login
curl -sS -b "${WORK}/cjar" http://127.0.0.1:8099/portal | grep -o 'Consent to treatment' | head -1
CT4="$(curl -sS -b "${WORK}/cjar" -c "${WORK}/cjar" http://127.0.0.1:8099/portal/forms/1 \
  | grep -o 'name="csrf_token" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')"
curl -sS -b "${WORK}/cjar" -o /dev/null -w 'sign: %{http_code}\n' \
  --data-urlencode "goals=Anxiety at work" \
  --data-urlencode "signature_name=Sam Rivera" \
  --data-urlencode "csrf_token=${CT4}" \
  http://127.0.0.1:8099/portal/forms/1

echo "==> signature evidence"
.venv/bin/python -c "
from app.database import SessionLocal
from app.models.forms import FormSubmission
from app.services import intake
db = SessionLocal()
for s in db.query(FormSubmission).all():
    print(f'  signed_by={s.signature_name!r} at={s.signed_at} ip={s.signature_ip}')
    print(f'  hash={s.document_hash[:16]}... intact={intake.signature_is_intact(s)}')
"

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
