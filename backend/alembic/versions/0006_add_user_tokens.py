"""add user tokens

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-07 19:39:57.921352

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "type IN ('email_verification', 'password_reset')",
            name=op.f("ck_user_tokens_type_is_known"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_tokens_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_tokens")),
    )
    op.create_index(
        "ix_user_tokens_user_id_type_created_at",
        "user_tokens",
        ["user_id", "type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_user_tokens_user_id_type_created_at", table_name="user_tokens")
    op.drop_table("user_tokens")
