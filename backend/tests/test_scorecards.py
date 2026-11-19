"""The interviewer's side: their interviews, the candidate, and blind scoring.

The rule that matters most: until an interviewer has submitted their own scorecard, the API never
returns anyone else's, however it is asked. Everything else here protects that rule or the scope
around it: an interviewer reaches only the interviews they are assigned to, only while the
interview is live do they see the candidate, and a scorecard is final.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations import storage
from app.models import (
    Application,
    ApplicationStage,
    AuditLog,
    CandidateProfile,
    File,
    Interview,
    InterviewStatus,
    Job,
    Note,
    PostingStatus,
    Role,
    Scorecard,
    User,
)
from tests.browser import Browser
from tests.factories import (
    make_application,
    make_candidate,
    make_company,
    make_department,
    make_interview,
    make_job,
    make_scorecard,
    make_user,
)
from tests.test_resume_files import MINIMAL_PDF

NOT_FOUND = {"detail": "Not found."}
LIST_FIELDS = {
    "id",
    "round_name",
    "scheduled_at",
    "duration_minutes",
    "location",
    "status",
    "job_title",
    "candidate_name",
    "my_scorecard_submitted",
}
DETAIL_FIELDS = {
    "id",
    "round_name",
    "scheduled_at",
    "duration_minutes",
    "location",
    "status",
    "job_title",
    "candidate",
    "my_scorecard",
    "others_visible",
    "others",
}
CANDIDATE_FIELDS = {"name", "email", "phone", "location"}
SCORECARD_FIELDS = {
    "id",
    "interviewer_name",
    "overall_rating",
    "technical_rating",
    "communication_rating",
    "problem_solving_rating",
    "culture_fit_rating",
    "feedback",
    "recommendation",
    "submitted_at",
}


@dataclass
class World:
    admin: User
    recruiter: User
    other_recruiter: User
    ivy: User  # interviewer on `interview`
    ian: User  # interviewer on `interview`
    ivo: User  # interviewer, not on `interview`
    cara: User
    application: Application
    interview: Interview  # scheduled, Ivy and Ian
    globex_interviewer: User
    globex_recruiter: User


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    admin = make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme)
    recruiter = make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme)
    other_recruiter = make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=acme)
    ivy = make_user(
        db, email="ivy@acme.test", role=Role.INTERVIEWER, company=acme, full_name="Ivy Inman"
    )
    ian = make_user(
        db, email="ian@acme.test", role=Role.INTERVIEWER, company=acme, full_name="Ian Ito"
    )
    ivo = make_user(db, email="ivo@acme.test", role=Role.INTERVIEWER, company=acme)
    job = make_job(
        db,
        company=acme,
        department=make_department(db, acme),
        created_by=admin,
        recruiters=[recruiter],
        status=PostingStatus.OPEN,
        title="Backend Engineer",
    )
    cara = make_candidate(db, email="cara@example.test", full_name="Cara Candidate")
    profile = db.get(CandidateProfile, cara.id)
    assert profile is not None
    profile.phone, profile.location = "+47 123 45 678", "Oslo"
    application = make_application(db, job=job, candidate=cara, stage=ApplicationStage.INTERVIEW)
    interview = make_interview(
        db, application=application, scheduled_by=recruiter, interviewers=[ivy, ian]
    )
    globex_interviewer = make_user(
        db, email="int@globex.test", role=Role.INTERVIEWER, company=globex
    )
    globex_recruiter = make_user(db, email="rec@globex.test", role=Role.RECRUITER, company=globex)
    db.commit()
    return World(
        admin,
        recruiter,
        other_recruiter,
        ivy,
        ian,
        ivo,
        cara,
        application,
        interview,
        globex_interviewer,
        globex_recruiter,
    )


def card(feedback: str = "Strong on systems design.", **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "overall_rating": 4,
        "technical_rating": 5,
        "communication_rating": 4,
        "problem_solving_rating": 3,
        "culture_fit_rating": 4,
        "feedback": feedback,
        "recommendation": "yes",
        **changes,
    }
    return body


def submit(browser: Browser, interview: Interview, **changes: Any) -> Response:
    return browser.send(
        "POST", f"/api/my/interviews/{interview.id}/scorecard", json=card(**changes)
    )


def detail(browser: Browser, interview: Interview) -> Response:
    return browser.get(f"/api/my/interviews/{interview.id}")


def stored(db: Session, interview: Interview) -> Interview:
    db.expire_all()
    fresh = db.get(Interview, interview.id)
    assert fresh is not None
    return fresh


def scorecards_in_db(db: Session) -> list[Scorecard]:
    db.expire_all()
    return list(db.scalars(select(Scorecard)))


def audit_rows(db: Session, action: str) -> list[AuditLog]:
    db.expire_all()
    return list(db.scalars(select(AuditLog).where(AuditLog.action == action)))


# ---- my interviews -----------------------------------------------------------------------------


def test_an_interviewer_sees_their_own_interviews_and_nobody_elses(
    client: TestClient, db: Session, world: World
) -> None:
    job = db.get(Job, world.application.job_id)
    assert job is not None
    elsewhere = make_application(
        db,
        job=job,
        candidate=make_candidate(db, email="dan@example.test"),
        stage=ApplicationStage.INTERVIEW,
    )
    make_interview(
        db, application=elsewhere, scheduled_by=world.recruiter, interviewers=[world.ivo]
    )
    db.commit()

    mine = Browser(client, db, world.ivy).get("/api/my/interviews").json()
    theirs = Browser(client, db, world.ivo).get("/api/my/interviews").json()

    assert [item["id"] for item in mine["items"]] == [str(world.interview.id)]
    assert mine["total"] == 1 and set(mine["items"][0]) == LIST_FIELDS
    assert len(theirs["items"]) == 1 and theirs["items"][0]["id"] != str(world.interview.id)


def test_the_list_says_who_and_what_without_anything_internal(
    client: TestClient, db: Session, world: World
) -> None:
    item = Browser(client, db, world.ivy).get("/api/my/interviews").json()["items"][0]

    assert item["job_title"] == "Backend Engineer" and item["candidate_name"] == "Cara Candidate"
    assert item["round_name"] == "Technical round" and item["status"] == "scheduled"
    assert item["my_scorecard_submitted"] is False


def test_the_list_can_be_narrowed_to_upcoming_or_awaiting(
    client: TestClient, db: Session, world: World
) -> None:
    past = make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ivy],
        scheduled_at=datetime.now(UTC) - timedelta(days=1),
        round_name="Yesterday",
    )
    scored = make_interview(
        db,
        application=world.application,
        scheduled_by=world.recruiter,
        interviewers=[world.ivy],
        scheduled_at=datetime.now(UTC) - timedelta(days=2),
        round_name="Scored already",
    )
    make_scorecard(db, interview=scored, interviewer=world.ivy)
    db.commit()
    browser = Browser(client, db, world.ivy)

    upcoming = browser.get("/api/my/interviews?filter=upcoming").json()["items"]
    awaiting = browser.get("/api/my/interviews?filter=awaiting").json()["items"]
    everything = browser.get("/api/my/interviews").json()["items"]

    assert [i["id"] for i in upcoming] == [str(world.interview.id)]  # still to come
    assert [i["id"] for i in awaiting] == [str(past.id)]  # over, and I have not scored it
    assert len(everything) == 3
    assert browser.get("/api/my/interviews?filter=bogus").status_code == 422


def test_the_list_is_paged(client: TestClient, db: Session, world: World) -> None:
    for number in range(3):
        make_interview(
            db,
            application=world.application,
            scheduled_by=world.recruiter,
            interviewers=[world.ivy],
            round_name=f"Round {number}",
        )
    db.commit()
    browser = Browser(client, db, world.ivy)

    first = browser.get("/api/my/interviews?page=1&page_size=3").json()
    second = browser.get("/api/my/interviews?page=2&page_size=3").json()

    assert first["total"] == 4 and len(first["items"]) == 3 and len(second["items"]) == 1


@pytest.mark.parametrize("who", ["recruiter", "admin", "cara"])
def test_only_interviewers_use_the_interviewer_routes(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    browser = Browser(client, db, getattr(world, who))

    assert browser.get("/api/my/interviews").status_code == 403
    assert detail(browser, world.interview).status_code == 403
    assert submit(browser, world.interview).status_code == 403
    assert browser.get(f"/api/my/interviews/{world.interview.id}/resume").status_code == 403


# ---- one interview -----------------------------------------------------------------------------


def test_an_interviewer_sees_the_interview_and_the_candidate(
    client: TestClient, db: Session, world: World
) -> None:
    response = detail(Browser(client, db, world.ivy), world.interview)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_FIELDS and set(body["candidate"]) == CANDIDATE_FIELDS
    assert body["candidate"] == {
        "name": "Cara Candidate",
        "email": "cara@example.test",
        "phone": "+47 123 45 678",
        "location": "Oslo",
    }
    assert body["job_title"] == "Backend Engineer" and body["location"] == "Room 4"
    assert body["my_scorecard"] is None and body["others_visible"] is False and body["others"] == []


def test_the_detail_holds_nothing_the_interviewer_may_not_see(
    client: TestClient, db: Session, world: World
) -> None:
    db.add(
        Note(
            application_id=world.application.id,
            company_id=world.admin.company_id,
            author_id=world.recruiter.id,
            body="INTERNAL-NOTE-TEXT",
        )
    )
    db.commit()

    text = detail(Browser(client, db, world.ivy), world.interview).text

    assert "INTERNAL-NOTE-TEXT" not in text
    for forbidden in ("rejection", "stage", "version", "notes", "resume_file"):
        assert forbidden not in text


@pytest.mark.parametrize("who", ["ivo", "globex_interviewer"])
def test_an_interviewer_not_assigned_gets_not_found_for_everything(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    browser = Browser(client, db, getattr(world, who))

    for response in (
        detail(browser, world.interview),
        submit(browser, world.interview),
        browser.get(f"/api/my/interviews/{world.interview.id}/resume"),
    ):
        assert response.status_code == 404 and response.json() == NOT_FOUND
    assert scorecards_in_db(db) == []


def test_an_unknown_interview_is_not_found(client: TestClient, db: Session, world: World) -> None:
    response = Browser(client, db, world.ivy).get(
        "/api/my/interviews/6f1c2d3e-0000-4000-8000-000000000000"
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


def test_once_an_interview_is_cancelled_the_candidate_is_no_longer_shown(
    client: TestClient, db: Session, world: World
) -> None:
    Browser(client, db, world.recruiter).send(
        "POST", f"/api/interviews/{world.interview.id}/cancel", json={"version": 1}
    )
    browser = Browser(client, db, world.ivy)

    body = detail(browser, world.interview).json()
    item = browser.get("/api/my/interviews").json()["items"][0]

    assert body["status"] == "cancelled" and body["candidate"] is None
    assert item["candidate_name"] is None  # the person may have been rejected or withdrawn
    assert "cara@example.test" not in detail(browser, world.interview).text


# ---- blind scoring -----------------------------------------------------------------------------


def test_nobody_elses_scorecard_is_visible_before_you_submit_your_own(
    client: TestClient, db: Session, world: World
) -> None:
    secret = "COLLEAGUE-FEEDBACK-TEXT"
    make_scorecard(db, interview=world.interview, interviewer=world.ian, feedback=secret)
    db.commit()

    response = detail(Browser(client, db, world.ivy), world.interview)

    body = response.json()
    assert body["others_visible"] is False and body["others"] == [] and body["my_scorecard"] is None
    assert secret not in response.text
    assert "Ian Ito" not in response.text  # not even who has already scored


def test_after_you_submit_you_see_your_colleagues_scorecards(
    client: TestClient, db: Session, world: World
) -> None:
    make_scorecard(db, interview=world.interview, interviewer=world.ian, feedback="Ian's view.")
    db.commit()
    browser = Browser(client, db, world.ivy)

    assert submit(browser, world.interview, feedback="Ivy's view.").status_code == 201
    body = detail(browser, world.interview).json()

    assert body["others_visible"] is True
    assert body["my_scorecard"]["feedback"] == "Ivy's view."
    assert [(c["interviewer_name"], c["feedback"]) for c in body["others"]] == [
        ("Ian Ito", "Ian's view.")
    ]
    assert all(set(c) == SCORECARD_FIELDS for c in [*body["others"], body["my_scorecard"]])


@pytest.mark.parametrize("first", ["ivy", "ian"])
def test_neither_sees_the_other_until_both_have_submitted_in_any_order(
    client: TestClient, db: Session, world: World, first: str
) -> None:
    second = "ian" if first == "ivy" else "ivy"
    one, two = getattr(world, first), getattr(world, second)

    assert (
        submit(Browser(client, db, one), world.interview, feedback="FIRST-VIEW").status_code == 201
    )
    # The first to submit still sees nothing of the second, who has not yet.
    before = detail(Browser(client, db, one), world.interview)
    assert before.json()["others"] == [] and "SECOND-VIEW" not in before.text
    # The second, who has not submitted, sees nothing of the first.
    blind = detail(Browser(client, db, two), world.interview)
    assert blind.json()["others_visible"] is False and "FIRST-VIEW" not in blind.text

    assert (
        submit(Browser(client, db, two), world.interview, feedback="SECOND-VIEW").status_code == 201
    )

    for me, view in ((one, "SECOND-VIEW"), (two, "FIRST-VIEW")):
        body = detail(Browser(client, db, me), world.interview).json()
        assert [c["feedback"] for c in body["others"]] == [view]


def test_a_submission_response_holds_only_the_callers_own_scorecard(
    client: TestClient, db: Session, world: World
) -> None:
    make_scorecard(db, interview=world.interview, interviewer=world.ian, feedback="HIDDEN-ONE")

    response = submit(Browser(client, db, world.ivy), world.interview)

    assert response.status_code == 201
    assert set(response.json()) == SCORECARD_FIELDS and "HIDDEN-ONE" not in response.text


# ---- submitting --------------------------------------------------------------------------------


def test_an_interviewer_submits_a_scorecard(client: TestClient, db: Session, world: World) -> None:
    response = submit(Browser(client, db, world.ivy), world.interview)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == SCORECARD_FIELDS and body["interviewer_name"] == "Ivy Inman"
    assert (body["overall_rating"], body["technical_rating"]) == (4, 5)
    assert body["recommendation"] == "yes" and body["feedback"] == "Strong on systems design."
    saved = scorecards_in_db(db)
    assert len(saved) == 1 and saved[0].interviewer_id == world.ivy.id


def test_submitting_is_audited_without_the_feedback_or_the_ratings(
    client: TestClient, db: Session, world: World
) -> None:
    submit(Browser(client, db, world.ivy), world.interview, feedback="PRIVATE-WORDS")

    rows = audit_rows(db, "scorecard.submitted")
    assert len(rows) == 1 and rows[0].actor_user_id == world.ivy.id
    assert rows[0].company_id == world.admin.company_id and rows[0].entity_type == "scorecard"
    assert rows[0].new_value == {"interview_id": str(world.interview.id)}
    assert "PRIVATE-WORDS" not in str(rows[0].new_value)


def test_the_feedback_is_trimmed(client: TestClient, db: Session, world: World) -> None:
    response = submit(Browser(client, db, world.ivy), world.interview, feedback="  padded  ")

    assert response.json()["feedback"] == "padded"


def test_a_second_submission_is_refused_and_changes_nothing(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.ivy)
    submit(browser, world.interview, feedback="THE FIRST WORD")

    again = submit(browser, world.interview, feedback="a different opinion", overall_rating=1)

    assert again.status_code == 409 and again.json()["code"] == "scorecard_already_submitted"
    only = scorecards_in_db(db)
    assert len(only) == 1 and only[0].feedback == "THE FIRST WORD" and only[0].overall_rating == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"overall_rating": 0},
        {"overall_rating": 6},
        {"technical_rating": 0},
        {"communication_rating": 6},
        {"problem_solving_rating": -1},
        {"culture_fit_rating": 7},
        {"overall_rating": 3.5},
        {"overall_rating": None},
        {"feedback": ""},
        {"feedback": "   \n "},
        {"feedback": "x" * 4001},
        {"recommendation": "maybe"},
        {"interviewer_id": "00000000-0000-0000-0000-000000000000"},  # never taken from the request
        {"interview_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_bad_scorecards_are_refused(
    client: TestClient, db: Session, world: World, changes: dict[str, Any]
) -> None:
    response = submit(Browser(client, db, world.ivy), world.interview, **changes)

    assert response.status_code == 422
    assert scorecards_in_db(db) == []


@pytest.mark.parametrize(
    "missing", ["overall_rating", "technical_rating", "feedback", "recommendation"]
)
def test_every_field_is_required(
    client: TestClient, db: Session, world: World, missing: str
) -> None:
    body = card()
    del body[missing]

    response = Browser(client, db, world.ivy).send(
        "POST", f"/api/my/interviews/{world.interview.id}/scorecard", json=body
    )

    assert response.status_code == 422


def test_the_edges_of_the_scale_are_accepted(client: TestClient, db: Session, world: World) -> None:
    response = submit(
        Browser(client, db, world.ivy),
        world.interview,
        overall_rating=1,
        technical_rating=5,
        feedback="x" * 4000,
        recommendation="strong_no",
    )

    assert response.status_code == 201


def test_a_cancelled_interview_takes_no_scorecard(
    client: TestClient, db: Session, world: World
) -> None:
    Browser(client, db, world.recruiter).send(
        "POST", f"/api/interviews/{world.interview.id}/cancel", json={"version": 1}
    )

    response = submit(Browser(client, db, world.ivy), world.interview)

    assert response.status_code == 409 and response.json()["code"] == "interview_not_scheduled"
    assert scorecards_in_db(db) == []


def test_scorecards_already_submitted_stay_readable_after_a_cancellation(
    client: TestClient, db: Session, world: World
) -> None:
    submit(Browser(client, db, world.ivy), world.interview, feedback="Said before the cancel.")
    Browser(client, db, world.recruiter).send(
        "POST", f"/api/interviews/{world.interview.id}/cancel", json={"version": 1}
    )

    body = detail(Browser(client, db, world.ivy), world.interview).json()

    assert body["my_scorecard"]["feedback"] == "Said before the cancel."


# ---- completing --------------------------------------------------------------------------------


def test_the_interview_completes_when_the_last_interviewer_submits(
    client: TestClient, db: Session, world: World
) -> None:
    submit(Browser(client, db, world.ivy), world.interview)
    assert stored(db, world.interview).status == InterviewStatus.SCHEDULED

    submit(Browser(client, db, world.ian), world.interview)

    done = stored(db, world.interview)
    assert done.status == InterviewStatus.COMPLETED and done.version == 2
    rows = audit_rows(db, "interview.completed")
    assert len(rows) == 1 and rows[0].new_value == {"status": "completed"}


def test_a_deactivated_interviewer_does_not_hold_the_interview_open(
    client: TestClient, db: Session, world: World
) -> None:
    world.ian.is_active = False
    db.commit()

    submit(Browser(client, db, world.ivy), world.interview)

    assert stored(db, world.interview).status == InterviewStatus.COMPLETED


def test_a_completed_interview_takes_no_further_scorecard_and_cannot_be_cancelled(
    client: TestClient, db: Session, world: World
) -> None:
    submit(Browser(client, db, world.ivy), world.interview)
    submit(Browser(client, db, world.ian), world.interview)

    again = submit(Browser(client, db, world.ian), world.interview)
    cancel = Browser(client, db, world.recruiter).send(
        "POST", f"/api/interviews/{world.interview.id}/cancel", json={"version": 2}
    )

    assert again.status_code == 409 and again.json()["code"] == "scorecard_already_submitted"
    assert cancel.status_code == 409 and cancel.json()["code"] == "interview_not_scheduled"


# ---- what staff see ----------------------------------------------------------------------------


def test_recruiters_and_admins_see_each_scorecard_as_soon_as_it_is_submitted(
    client: TestClient, db: Session, world: World
) -> None:
    submit(Browser(client, db, world.ivy), world.interview, feedback="Only Ivy has scored.")

    for person in (world.recruiter, world.admin):
        response = Browser(client, db, person).get(
            f"/api/interviews/{world.interview.id}/scorecards"
        )

        assert response.status_code == 200
        assert [c["feedback"] for c in response.json()] == ["Only Ivy has scored."]
        assert set(response.json()[0]) == SCORECARD_FIELDS


def test_an_interview_nobody_has_scored_has_an_empty_list(
    client: TestClient, db: Session, world: World
) -> None:
    response = Browser(client, db, world.recruiter).get(
        f"/api/interviews/{world.interview.id}/scorecards"
    )

    assert response.status_code == 200 and response.json() == []


@pytest.mark.parametrize("who", ["ivy", "cara"])
def test_interviewers_and_candidates_cannot_use_the_staff_scorecard_route(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    # Not even an interviewer who has submitted: their route is /api/my/interviews.
    submit(Browser(client, db, world.ivy), world.interview)

    response = Browser(client, db, getattr(world, who)).get(
        f"/api/interviews/{world.interview.id}/scorecards"
    )

    assert response.status_code == 403


@pytest.mark.parametrize("who", ["other_recruiter", "globex_recruiter"])
def test_staff_outside_the_job_get_not_found_for_the_scorecards(
    client: TestClient, db: Session, world: World, who: str
) -> None:
    make_scorecard(db, interview=world.interview, interviewer=world.ivy)
    db.commit()

    response = Browser(client, db, getattr(world, who)).get(
        f"/api/interviews/{world.interview.id}/scorecards"
    )

    assert response.status_code == 404 and response.json() == NOT_FOUND


def test_an_interviewer_who_has_scored_cannot_be_removed_from_the_interview(
    client: TestClient, db: Session, world: World
) -> None:
    submit(Browser(client, db, world.ivy), world.interview)
    browser = Browser(client, db, world.recruiter)

    refused = browser.send(
        "PATCH",
        f"/api/interviews/{world.interview.id}",
        json={"version": 1, "interviewer_ids": [str(world.ian.id)]},
    )
    allowed = browser.send(
        "PATCH",
        f"/api/interviews/{world.interview.id}",
        json={"version": 1, "interviewer_ids": [str(world.ivy.id)]},
    )

    assert refused.status_code == 409 and refused.json()["code"] == "interviewer_has_scored"
    assert allowed.status_code == 200  # Ian had not scored, so he can go
    assert len(scorecards_in_db(db)) == 1


# ---- the resume --------------------------------------------------------------------------------


def put_resume(db: Session, world: World) -> None:
    file = db.get(File, world.application.resume_file_id)
    assert file is not None
    storage.put_object(file.storage_key, MINIMAL_PDF, file.content_type)


def test_an_assigned_interviewer_downloads_the_resume_the_candidate_applied_with(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    put_resume(db, world)

    response = Browser(client, db, world.ivy).get(f"/api/my/interviews/{world.interview.id}/resume")

    assert response.status_code == 200 and response.content == MINIMAL_PDF
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]


def test_the_resume_is_not_served_once_the_interview_is_cancelled(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    put_resume(db, world)
    Browser(client, db, world.recruiter).send(
        "POST", f"/api/interviews/{world.interview.id}/cancel", json={"version": 1}
    )

    response = Browser(client, db, world.ivy).get(f"/api/my/interviews/{world.interview.id}/resume")

    assert response.status_code == 404 and response.json() == NOT_FOUND


def test_the_resume_of_an_interview_you_are_not_on_is_not_found(
    client: TestClient, db: Session, world: World, storage_bucket: str
) -> None:
    put_resume(db, world)

    response = Browser(client, db, world.ivo).get(f"/api/my/interviews/{world.interview.id}/resume")

    assert response.status_code == 404 and response.json() == NOT_FOUND


# ---- what the database refuses -----------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"overall_rating": 0},
        {"overall_rating": 6},
        {"culture_fit_rating": 0},
        {"feedback": "   "},
    ],
)
def test_the_database_refuses_a_nonsense_scorecard(
    db: Session, world: World, changes: dict[str, Any]
) -> None:
    scorecard = make_scorecard(db, interview=world.interview, interviewer=world.ivy)
    for name, value in changes.items():
        setattr(scorecard, name, value)

    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_the_database_refuses_a_scorecard_from_someone_not_on_the_interview(
    db: Session, world: World
) -> None:
    with pytest.raises(IntegrityError):
        make_scorecard(db, interview=world.interview, interviewer=world.ivo)
    db.rollback()


def test_the_database_refuses_a_second_scorecard_from_the_same_interviewer(
    db: Session, world: World
) -> None:
    make_scorecard(db, interview=world.interview, interviewer=world.ivy)
    with pytest.raises(IntegrityError):
        make_scorecard(db, interview=world.interview, interviewer=world.ivy)
    db.rollback()
