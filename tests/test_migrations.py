"""The migration chain must produce the schema the models describe.

Alembic owns the schema (CLAUDE.md), but the test suite builds its database with
`create_all`. Without this test the two can drift silently, and the drift only
surfaces on a real deployment. Running the chain against a throwaway SQLite file
catches the common cases — a column added to a model but not to a migration, and
a migration that does not reverse cleanly.
"""
import os
import tempfile

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.database import Base

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tables the migrations own. Kept explicit so a new table without a migration
# fails here rather than being quietly skipped.
EXPECTED_TABLES = {
    "tenants",
    "users",
    "user_sessions",
    "audit_logs",
    "therapist_profiles",
    "therapist_licenses",
    "clients",
    "appointments",
    "payments",
    "clinical_notes",
    "note_addenda",
}


@pytest.fixture
def migrated_url():
    """A SQLite database brought to head by the real migration chain."""
    path = os.path.join(tempfile.mkdtemp(prefix="care-migrate-"), "m.db")
    url = f"sqlite:///{path}"
    cfg = Config(os.path.join(_ROOT, "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url, cfg


def test_chain_runs_to_head(migrated_url):
    url, _ = migrated_url
    tables = set(inspect(create_engine(url)).get_table_names())
    assert EXPECTED_TABLES <= tables


def test_every_model_table_is_migrated(migrated_url):
    url, _ = migrated_url
    migrated = set(inspect(create_engine(url)).get_table_names())
    modelled = set(Base.metadata.tables)
    missing = modelled - migrated
    assert not missing, f"models define tables with no migration: {sorted(missing)}"


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_migrated_columns_match_the_models(migrated_url, table):
    url, _ = migrated_url
    migrated = {c["name"] for c in inspect(create_engine(url)).get_columns(table)}
    modelled = set(Base.metadata.tables[table].columns.keys())
    assert modelled == migrated, (
        f"{table}: models and migrations disagree — "
        f"only in models: {sorted(modelled - migrated)}, "
        f"only in migrations: {sorted(migrated - modelled)}"
    )


def test_tenant_owned_tables_carry_tenant_id(migrated_url):
    """CLAUDE.md's multi-tenancy rule, enforced against the real schema.

    `tenants` is exempt (it *is* the tenant); every other table here is
    tenant-owned and must carry the column.
    """
    url, _ = migrated_url
    inspector = inspect(create_engine(url))
    for table in EXPECTED_TABLES - {"tenants"}:
        columns = {c["name"] for c in inspector.get_columns(table)}
        assert "tenant_id" in columns, f"{table} is missing tenant_id"


def test_downgrade_reverses_cleanly(migrated_url):
    """A migration that cannot be rolled back is a migration you cannot deploy
    with confidence."""
    url, cfg = migrated_url
    command.downgrade(cfg, "0001_initial")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert "user_sessions" not in tables
    assert "audit_logs" not in tables

    users = {c["name"] for c in inspect(create_engine(url)).get_columns("users")}
    assert "password_hash" not in users
