"""add heartbeat deployment id

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06 15:33:14.435331

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "worker_heartbeats", sa.Column("deployment_id", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("worker_heartbeats", "deployment_id")
