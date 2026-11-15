"""What the database itself refuses about a rejection, whatever the application code does."""

from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ApplicationStage, PostingStatus, RejectionReason, Role
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_job,
    make_user,
)


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": ApplicationStage.REJECTED},  # a rejection with no reason
        {"rejection_reason": RejectionReason.SKILLS_MISMATCH},  # a reason without a rejection
        {
            "stage": ApplicationStage.REJECTED,
            "rejected_from_stage": ApplicationStage.HIRED,
            "rejection_reason": RejectionReason.SKILLS_MISMATCH,
        },  # cannot have been rejected from a stage that was already final
        {
            "stage": ApplicationStage.REJECTED,
            "rejected_from_stage": ApplicationStage.APPLIED,
            "rejection_reason": RejectionReason.OTHER,
        },  # "other" must explain itself
        {
            "stage": ApplicationStage.REJECTED,
            "rejected_from_stage": ApplicationStage.APPLIED,
            "rejection_reason": RejectionReason.OTHER,
            "rejection_comment": "   ",
        },  # ...with words, not spaces
        {"rejection_comment": "a comment on an application that is not rejected"},
    ],
)
def test_the_database_refuses_an_inconsistent_rejection(
    db: Session, changes: dict[str, Any]
) -> None:
    company = make_company(db)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        status=PostingStatus.OPEN,
    )
    application = make_application(db, job=job, candidate=make_candidate(db, email="y@x.test"))
    db.commit()
    for name, value in changes.items():
        setattr(application, name, value)

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_the_database_accepts_a_consistent_rejection(db: Session) -> None:
    company = make_company(db)
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company)
    job = make_job(
        db,
        company=company,
        department=make_department(db, company),
        created_by=admin,
        status=PostingStatus.OPEN,
    )
    application = make_application(db, job=job, candidate=make_candidate(db, email="y@x.test"))
    application.stage = ApplicationStage.REJECTED
    application.rejected_from_stage = ApplicationStage.SCREENING
    application.rejection_reason = RejectionReason.OTHER
    application.rejection_comment = "Withdrew interest by phone"

    db.commit()  # no error
