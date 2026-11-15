"""add the rejection to applications

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-15 16:04:34.913510

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGES = "'applied', 'screening', 'interview', 'offer', 'hired', 'rejected', 'withdrawn'"
REASONS = (
    "'skills_mismatch', 'position_filled', 'candidate_unresponsive', 'failed_interview', 'other'"
)


def upgrade() -> None:
    """Upgrade schema. Additive only: the three columns are empty for every existing row."""
    # `add_column` does not create the CHECK that an Enum column carries, so the checks are
    # written out below (named as the models name them).
    op.add_column(
        "applications", sa.Column("rejected_from_stage", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "applications", sa.Column("rejection_reason", sa.String(length=30), nullable=True)
    )
    op.add_column("applications", sa.Column("rejection_comment", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_applications_application_rejected_from_stage_is_known"),
        "applications",
        f"rejected_from_stage IN ({STAGES})",
    )
    op.create_check_constraint(
        op.f("ck_applications_application_rejection_reason_is_known"),
        "applications",
        f"rejection_reason IN ({REASONS})",
    )
    op.create_check_constraint(
        op.f("ck_applications_rejection_matches_stage"),
        "applications",
        "(stage = 'rejected') = (rejection_reason IS NOT NULL) AND "
        "(stage = 'rejected') = (rejected_from_stage IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_applications_rejection_from_active_stage"),
        "applications",
        "rejected_from_stage IS NULL OR "
        "rejected_from_stage IN ('applied', 'screening', 'interview', 'offer')",
    )
    op.create_check_constraint(
        op.f("ck_applications_rejection_other_has_comment"),
        "applications",
        "rejection_reason IS DISTINCT FROM 'other' OR "
        "(rejection_comment IS NOT NULL AND length(btrim(rejection_comment)) > 0)",
    )
    op.create_check_constraint(
        op.f("ck_applications_rejection_comment_only_when_rejected"),
        "applications",
        "rejection_comment IS NULL OR stage = 'rejected'",
    )


def downgrade() -> None:
    """Downgrade schema."""
    for name in (
        "rejection_comment_only_when_rejected",
        "rejection_other_has_comment",
        "rejection_from_active_stage",
        "rejection_matches_stage",
        "application_rejection_reason_is_known",
        "application_rejected_from_stage_is_known",
    ):
        op.drop_constraint(op.f(f"ck_applications_{name}"), "applications", type_="check")
    op.drop_column("applications", "rejection_comment")
    op.drop_column("applications", "rejection_reason")
    op.drop_column("applications", "rejected_from_stage")
