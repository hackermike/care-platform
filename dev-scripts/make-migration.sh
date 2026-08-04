#!/usr/bin/env bash
# Autogenerate an Alembic migration from model changes. Review the result before
# committing (prefer nullable columns; check tenant_id is present on new tables).
#   ./dev-scripts/make-migration.sh "short description"
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${1:-}" ]; then
  echo "usage: $0 \"short description\"" >&2
  exit 1
fi

.venv/bin/alembic revision --autogenerate -m "$1"
echo "Review the new file in migrations/versions/ before committing."
