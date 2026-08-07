"""M1: real auth, tenant branding, sessions, and the audit log

Adds the foundation from docs/MILESTONES.md M1:

* tenant white-label branding (the client portal is per-network branded)
* user credentials, activation state, and failed-login throttling
* server-side sessions, so revocation is immediate
* the append-only audit log

New user columns are nullable or defaulted, so the migration is safe against a
table that already holds rows (CLAUDE.md: prefer nullable columns).

Revision ID: 0002_auth_tenancy
Revises: 0001_initial
Create Date: 2026-08-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_auth_tenancy"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table throughout: on Postgres it emits plain ALTERs, and on
    # SQLite it falls back to table-rebuild. Keeping it portable lets the test
    # suite run the migration chain without a Postgres instance.

    # --- tenants: white-label branding + activation -------------------------
    op.add_column("tenants", sa.Column("is_active", sa.Boolean(), nullable=True))
    op.execute("UPDATE tenants SET is_active = 1 WHERE is_active IS NULL")
    with op.batch_alter_table("tenants") as batch:
        batch.alter_column(
            "is_active",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        )
    op.add_column("tenants", sa.Column("brand_name", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("brand_color", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("logo_url", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("support_email", sa.String(), nullable=True))

    # --- users: credentials, state, throttling ------------------------------
    op.add_column("users", sa.Column("full_name", sa.String(), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("failed_login_count", sa.Integer(), nullable=True))
    op.add_column(
        "users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE users SET is_active = 1 WHERE is_active IS NULL")
    op.execute("UPDATE users SET failed_login_count = 0 WHERE failed_login_count IS NULL")
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "is_active",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        )
        batch.alter_column(
            "failed_login_count",
            existing_type=sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        )
        # Email is unique per tenant, not globally: the same person may be a
        # client of one network and a therapist in another.
        batch.create_unique_constraint("uq_users_tenant_email", ["tenant_id", "email"])

    # --- server-side sessions ----------------------------------------------
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_user_sessions_tenant_id", "user_sessions", ["tenant_id"])
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"])

    # --- audit log ----------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        # Nullable: a failed login can arrive before a tenant is resolved.
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_user_sessions_token_hash", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_tenant_id", table_name="user_sessions")
    op.drop_table("user_sessions")

    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_tenant_email", type_="unique")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "is_active")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "full_name")

    op.drop_column("tenants", "support_email")
    op.drop_column("tenants", "logo_url")
    op.drop_column("tenants", "brand_color")
    op.drop_column("tenants", "brand_name")
    op.drop_column("tenants", "is_active")
