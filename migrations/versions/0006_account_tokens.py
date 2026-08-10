"""Account tokens: invitations and password resets

The token is a credential — anyone holding it can set a password on the account
— so only its SHA-256 is stored, exactly as for passwords and sessions.
`consumed_at` marks single use rather than deleting the row, because "already
used" and "never existed" are different answers and an incident review needs to
tell them apart.

Revision ID: 0006_account_tokens
Revises: 0005_intake_forms
Create Date: 2026-08-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_account_tokens"
down_revision: Union[str, Sequence[str], None] = "0005_intake_forms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", sa.String(), nullable=True),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_account_tokens_tenant_id", "account_tokens", ["tenant_id"])
    op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])
    op.create_index("ix_account_tokens_token_hash", "account_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_account_tokens_token_hash", table_name="account_tokens")
    op.drop_index("ix_account_tokens_user_id", table_name="account_tokens")
    op.drop_index("ix_account_tokens_tenant_id", table_name="account_tokens")
    op.drop_table("account_tokens")
