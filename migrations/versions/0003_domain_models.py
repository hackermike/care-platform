"""M2: the breakout-core domain, multi-tenant

Adds the tables whose shapes satisfy breakout-core's Protocols
(docs/INTEGRATION.md): therapist profiles and licences, clients, appointments,
and payments.

Money is Numeric(10, 2), not float — see app/models/money.py for why the
breakout-core boundary differs from storage.

Every table carries tenant_id (CLAUDE.md's multi-tenancy rule).

Revision ID: 0003_domain_models
Revises: 0002_auth_tenancy
Create Date: 2026-08-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_domain_models"
down_revision: Union[str, Sequence[str], None] = "0002_auth_tenancy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(10, 2)


def upgrade() -> None:
    op.create_table(
        "therapist_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("credentials", sa.String(), nullable=True),
        sa.Column("npi", sa.String(), nullable=True),
        sa.Column("license_number", sa.String(), nullable=True),
        sa.Column("tax_id", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("practice_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", name="uq_therapist_profiles_user"),
    )
    op.create_index("ix_therapist_profiles_tenant_id", "therapist_profiles", ["tenant_id"])
    op.create_index("ix_therapist_profiles_user_id", "therapist_profiles", ["user_id"])

    op.create_table(
        "therapist_licenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "therapist_id",
            sa.Integer(),
            sa.ForeignKey("therapist_profiles.id"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column("license_number", sa.String(), nullable=True),
        sa.Column("expires_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "therapist_id", "state", name="uq_therapist_licenses_therapist_state"
        ),
    )
    op.create_index("ix_therapist_licenses_tenant_id", "therapist_licenses", ["tenant_id"])
    op.create_index(
        "ix_therapist_licenses_therapist_id", "therapist_licenses", ["therapist_id"]
    )

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "therapist_id",
            sa.Integer(),
            sa.ForeignKey("therapist_profiles.id"),
            nullable=True,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=False),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("diagnosis_codes", sa.String(), nullable=True),
        sa.Column("insurance_company", sa.String(), nullable=True),
        sa.Column("insurance_id", sa.String(), nullable=True),
        sa.Column("group_number", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("state", sa.String(length=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_clients_tenant_id", "clients", ["tenant_id"])
    op.create_index("ix_clients_therapist_id", "clients", ["therapist_id"])
    op.create_index("ix_clients_user_id", "clients", ["user_id"])

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column(
            "therapist_id",
            sa.Integer(),
            sa.ForeignKey("therapist_profiles.id"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "written_off", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("fee_amount", MONEY, nullable=True),
        sa.Column("cpt_code", sa.String(), nullable=True),
        sa.Column("modifier_1", sa.String(), nullable=True),
        sa.Column("modifier_2", sa.String(), nullable=True),
        sa.Column("diagnosis_codes", sa.String(), nullable=True),
        sa.Column("place_of_service", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_appointments_tenant_id", "appointments", ["tenant_id"])
    op.create_index("ix_appointments_client_id", "appointments", ["client_id"])
    op.create_index("ix_appointments_therapist_id", "appointments", ["therapist_id"])
    op.create_index("ix_appointments_starts_at", "appointments", ["starts_at"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "appointment_id",
            sa.Integer(),
            sa.ForeignKey("appointments.id"),
            nullable=False,
        ),
        sa.Column("amount_value", MONEY, nullable=False),
        sa.Column("servicer_fee_value", MONEY, nullable=True),
        sa.Column(
            "is_refund", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"])
    op.create_index("ix_payments_appointment_id", "payments", ["appointment_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_appointment_id", table_name="payments")
    op.drop_index("ix_payments_tenant_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_appointments_starts_at", table_name="appointments")
    op.drop_index("ix_appointments_therapist_id", table_name="appointments")
    op.drop_index("ix_appointments_client_id", table_name="appointments")
    op.drop_index("ix_appointments_tenant_id", table_name="appointments")
    op.drop_table("appointments")

    op.drop_index("ix_clients_user_id", table_name="clients")
    op.drop_index("ix_clients_therapist_id", table_name="clients")
    op.drop_index("ix_clients_tenant_id", table_name="clients")
    op.drop_table("clients")

    op.drop_index("ix_therapist_licenses_therapist_id", table_name="therapist_licenses")
    op.drop_index("ix_therapist_licenses_tenant_id", table_name="therapist_licenses")
    op.drop_table("therapist_licenses")

    op.drop_index("ix_therapist_profiles_user_id", table_name="therapist_profiles")
    op.drop_index("ix_therapist_profiles_tenant_id", table_name="therapist_profiles")
    op.drop_table("therapist_profiles")
