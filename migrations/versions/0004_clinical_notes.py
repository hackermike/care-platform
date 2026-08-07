"""M3: clinical notes and addenda

A signed note is locked; corrections are made by addendum rather than by editing,
so the record shows both what was written at the time and what was corrected
later. That is why addenda are a separate table instead of an editable field.

Progress and psychotherapy notes are distinguished by `kind` because HIPAA holds
them to different disclosure standards.

Revision ID: 0004_clinical_notes
Revises: 0003_domain_models
Create Date: 2026-08-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_clinical_notes"
down_revision: Union[str, Sequence[str], None] = "0003_domain_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clinical_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "appointment_id",
            sa.Integer(),
            sa.ForeignKey("appointments.id"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("therapist_profiles.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_clinical_notes_tenant_id", "clinical_notes", ["tenant_id"])
    op.create_index(
        "ix_clinical_notes_appointment_id", "clinical_notes", ["appointment_id"]
    )
    op.create_index("ix_clinical_notes_author_id", "clinical_notes", ["author_id"])

    op.create_table(
        "note_addenda",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "note_id", sa.Integer(), sa.ForeignKey("clinical_notes.id"), nullable=False
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("therapist_profiles.id"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_note_addenda_tenant_id", "note_addenda", ["tenant_id"])
    op.create_index("ix_note_addenda_note_id", "note_addenda", ["note_id"])
    op.create_index("ix_note_addenda_author_id", "note_addenda", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_note_addenda_author_id", table_name="note_addenda")
    op.drop_index("ix_note_addenda_note_id", table_name="note_addenda")
    op.drop_index("ix_note_addenda_tenant_id", table_name="note_addenda")
    op.drop_table("note_addenda")

    op.drop_index("ix_clinical_notes_author_id", table_name="clinical_notes")
    op.drop_index("ix_clinical_notes_appointment_id", table_name="clinical_notes")
    op.drop_index("ix_clinical_notes_tenant_id", table_name="clinical_notes")
    op.drop_table("clinical_notes")
