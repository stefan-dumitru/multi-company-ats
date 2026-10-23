"""Empty starting point.

Phase 0 has no tables; this revision exists so migrations, the /ready check and the CI
"apply from scratch" step all have something real to run. Phase 2 adds the first tables.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
