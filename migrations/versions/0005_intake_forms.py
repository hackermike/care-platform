"""M4: intake forms, consent documents, and signatures

`form_submissions.document_hash` is the load-bearing column: it stores a SHA-256
of the exact text and questions presented at signing time, so editing a consent
template later cannot silently change what a past client appears to have agreed
to.

Revision ID: 0005_intake_forms
Revises: 0004_clinical_notes
Create Date: 2026-08-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_intake_forms"
down_revision: Union[str, Sequence[str], None] = "0004_clinical_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "form_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("schema_json", sa.Text(), nullable=True),
        sa.Column(
            "requires_signature",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_form_templates_tenant_id", "form_templates", ["tenant_id"])

    op.create_table(
        "form_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("form_templates.id"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_form_assignments_tenant_id", "form_assignments", ["tenant_id"])
    op.create_index(
        "ix_form_assignments_template_id", "form_assignments", ["template_id"]
    )
    op.create_index("ix_form_assignments_client_id", "form_assignments", ["client_id"])

    op.create_table(
        "form_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("form_templates.id"),
            nullable=False,
        ),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            sa.ForeignKey("form_assignments.id"),
            nullable=True,
        ),
        sa.Column(
            "submitted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("answers_json", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_name", sa.String(), nullable=True),
        sa.Column("document_hash", sa.String(), nullable=True),
        sa.Column("signature_ip", sa.String(), nullable=True),
        sa.Column("signature_user_agent", sa.String(), nullable=True),
    )
    op.create_index("ix_form_submissions_tenant_id", "form_submissions", ["tenant_id"])
    op.create_index(
        "ix_form_submissions_template_id", "form_submissions", ["template_id"]
    )
    op.create_index("ix_form_submissions_client_id", "form_submissions", ["client_id"])
    op.create_index(
        "ix_form_submissions_assignment_id", "form_submissions", ["assignment_id"]
    )
    op.create_index(
        "ix_form_submissions_submitted_by_id", "form_submissions", ["submitted_by_id"]
    )


def downgrade() -> None:
    for index in (
        "ix_form_submissions_submitted_by_id",
        "ix_form_submissions_assignment_id",
        "ix_form_submissions_client_id",
        "ix_form_submissions_template_id",
        "ix_form_submissions_tenant_id",
    ):
        op.drop_index(index, table_name="form_submissions")
    op.drop_table("form_submissions")

    for index in (
        "ix_form_assignments_client_id",
        "ix_form_assignments_template_id",
        "ix_form_assignments_tenant_id",
    ):
        op.drop_index(index, table_name="form_assignments")
    op.drop_table("form_assignments")

    op.drop_index("ix_form_templates_tenant_id", table_name="form_templates")
    op.drop_table("form_templates")
