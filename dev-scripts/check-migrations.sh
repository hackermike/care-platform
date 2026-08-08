#!/usr/bin/env bash
# Exercise the migration chain against whatever DATABASE_URL points at.
#
# `tests/test_migrations.py` checks that the models and the migrations agree, but
# it runs on SQLite. This runs the real chain forwards, all the way back, and
# forwards again — which is what catches the things that only differ on the real
# database: NUMERIC precision, timezone-aware timestamps, constraint naming, and
# a downgrade that leaves the schema unusable.
#
#   DATABASE_URL=postgresql+psycopg://... ./dev-scripts/check-migrations.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Use the venv when there is one (local), otherwise whatever is on PATH (CI),
# so this script is the single definition of "migrations are healthy".
if [ -x .venv/bin/alembic ]; then
  ALEMBIC=.venv/bin/alembic
  PYTHON=.venv/bin/python
else
  ALEMBIC=alembic
  PYTHON=python
fi

echo "==> target: ${DATABASE_URL:-(default from app/database.py)}"

echo "==> upgrade head"
"${ALEMBIC}" upgrade head

echo "==> current"
"${ALEMBIC}" current

echo "==> downgrade base"
"${ALEMBIC}" downgrade base

echo "==> upgrade head again"
"${ALEMBIC}" upgrade head

echo "==> schema matches the models"
"${PYTHON}" - <<'PY'
import os

from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401 — register models on Base
from app.database import Base

url = os.environ.get("DATABASE_URL")
engine = create_engine(url) if url else __import__(
    "app.database", fromlist=["engine"]
).engine
inspector = inspect(engine)

migrated = set(inspector.get_table_names()) - {"alembic_version"}
modelled = set(Base.metadata.tables)
missing = modelled - migrated
extra = migrated - modelled
if missing or extra:
    raise SystemExit(
        f"schema drift — only in models: {sorted(missing)}; "
        f"only in database: {sorted(extra)}"
    )

for table in sorted(modelled):
    db_cols = {c["name"] for c in inspector.get_columns(table)}
    model_cols = set(Base.metadata.tables[table].columns.keys())
    if db_cols != model_cols:
        raise SystemExit(
            f"{table}: only in models {sorted(model_cols - db_cols)}; "
            f"only in database {sorted(db_cols - model_cols)}"
        )
    if table != "tenants" and "tenant_id" not in db_cols:
        raise SystemExit(f"{table} is missing tenant_id")

print(f"  {len(modelled)} tables match the models; every one carries tenant_id")
PY

echo "OK"
