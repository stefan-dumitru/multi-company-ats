"""The public job pages (functional.md > Search; SPECS.md Phase 4): anyone, logged in or not, can
list and read OPEN jobs of every company, and nothing else.

The most important property is what must never appear: drafts, closed jobs, and anything that is
internal (recruiters, creators, ids of staff). Several tests attack that from different sides.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session

from app.models import Company, Department, Job, PostingStatus, Role, User
from tests.browser import Browser
from tests.factories import make_company, make_department, make_job, make_user

NOT_FOUND = {"detail": "Not found."}
SUMMARY_FIELDS = {
    "id",
    "title",
    "location",
    "excerpt",
    "department_name",
    "company_id",
    "company_name",
    "opened_at",
}
DETAIL_FIELDS = (SUMMARY_FIELDS - {"excerpt"}) | {"description"}


@dataclass
class World:
    acme: Company
    globex: Company
    acme_admin: User
    acme_rec: User
    candidate: User
    acme_dept: Department
    globex_dept: Department


@pytest.fixture
def world(db: Session) -> World:
    acme, globex = make_company(db, "Acme"), make_company(db, "Globex")
    built = World(
        acme=acme,
        globex=globex,
        acme_admin=make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=acme),
        acme_rec=make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=acme),
        candidate=make_user(db, email="cand@example.test", role=Role.CANDIDATE, company=None),
        acme_dept=make_department(db, acme, "Engineering"),
        globex_dept=make_department(db, globex, "Platform"),
    )
    db.commit()
    return built


def new_job(db: Session, world: World, company: str = "acme", **kwargs: Any) -> Job:
    """A job of Acme or Globex, not yet committed."""
    acme = company == "acme"
    return make_job(
        db,
        company=world.acme if acme else world.globex,
        department=world.acme_dept if acme else world.globex_dept,
        created_by=world.acme_admin,
        **kwargs,
    )


def open_job(world: World, db: Session, company: str = "acme", **kwargs: Any) -> Job:
    job = new_job(db, world, company, status=PostingStatus.OPEN, **kwargs)
    db.commit()
    return job


def titles(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


# ---- what is visible ---------------------------------------------------------------------


def test_anyone_sees_open_jobs_of_every_company(
    client: TestClient, db: Session, world: World
) -> None:
    open_job(world, db, title="Acme engineer")
    open_job(world, db, company="globex", title="Globex designer")

    response = client.get("/api/public/jobs")

    assert sorted(titles(response)) == ["Acme engineer", "Globex designer"]
    assert response.json()["total"] == 2


def test_drafts_and_closed_jobs_never_appear(client: TestClient, db: Session, world: World) -> None:
    open_job(world, db, title="Visible")
    new_job(db, world, title="Secret draft", status=PostingStatus.DRAFT)
    new_job(db, world, title="Old closed", status=PostingStatus.CLOSED)
    new_job(db, world, company="globex", title="Globex draft", status=PostingStatus.DRAFT)
    db.commit()

    response = client.get("/api/public/jobs")

    assert titles(response) == ["Visible"]
    assert response.json()["total"] == 1


def test_a_logged_in_recruiter_sees_the_same_public_list_not_their_own_drafts(
    client: TestClient, db: Session, world: World
) -> None:
    open_job(world, db, title="Visible", recruiters=[world.acme_rec])
    new_job(db, world, title="My own draft", recruiters=[world.acme_rec])
    db.commit()
    Browser(client, db, world.acme_rec)

    assert titles(client.get("/api/public/jobs")) == ["Visible"]


def test_only_the_whitelisted_fields_are_exposed(
    client: TestClient, db: Session, world: World
) -> None:
    job = open_job(world, db, recruiters=[world.acme_rec])

    summary = client.get("/api/public/jobs").json()["items"][0]
    detail = client.get(f"/api/public/jobs/{job.id}").json()

    assert set(summary) == SUMMARY_FIELDS
    assert set(detail) == DETAIL_FIELDS
    everything = str(summary) + str(detail)
    for private in (str(world.acme_admin.id), str(world.acme_rec.id), "rec@acme.test"):
        assert private not in everything


def test_the_list_shows_company_department_and_a_short_excerpt(
    client: TestClient, db: Session, world: World
) -> None:
    open_job(world, db, description="word " * 200)

    item = client.get("/api/public/jobs").json()["items"][0]

    assert item["company_name"] == "Acme" and item["department_name"] == "Engineering"
    assert item["company_id"] == str(world.acme.id)
    assert 0 < len(item["excerpt"]) <= 300
    assert "description" not in item  # the whole text is for the detail page


# ---- one job -----------------------------------------------------------------------------


def test_an_open_job_can_be_read_in_full_by_anyone(
    client: TestClient, db: Session, world: World
) -> None:
    job = open_job(world, db, title="Staff engineer", description="Long text here.")

    response = client.get(f"/api/public/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Staff engineer" and body["description"] == "Long text here."
    assert body["company_name"] == "Acme" and body["department_name"] == "Engineering"


def test_drafts_closed_and_unknown_jobs_all_answer_the_same_not_found(
    client: TestClient, db: Session, world: World
) -> None:
    draft = new_job(db, world, status=PostingStatus.DRAFT)
    closed = new_job(db, world, status=PostingStatus.CLOSED)
    db.commit()

    for job_id in (draft.id, closed.id, uuid.uuid4()):
        response = client.get(f"/api/public/jobs/{job_id}")
        assert response.status_code == 404 and response.json() == NOT_FOUND


def test_a_job_disappears_when_closed_and_appears_when_opened(
    client: TestClient, db: Session, world: World
) -> None:
    job = new_job(db, world, status=PostingStatus.DRAFT)
    db.commit()
    assert client.get(f"/api/public/jobs/{job.id}").status_code == 404

    job.status = PostingStatus.OPEN
    job.opened_at = datetime.now(UTC)
    db.commit()
    assert client.get(f"/api/public/jobs/{job.id}").status_code == 200

    job.status = PostingStatus.CLOSED
    db.commit()
    assert client.get(f"/api/public/jobs/{job.id}").status_code == 404
    assert titles(client.get("/api/public/jobs")) == []


# ---- keyword search ----------------------------------------------------------------------


def test_a_keyword_matches_the_title_or_the_description(
    client: TestClient, db: Session, world: World
) -> None:
    open_job(world, db, title="Data analyst", description="Work with SQL and dashboards.")
    open_job(world, db, title="Designer", description="Make interfaces and brand identity.")

    assert titles(client.get("/api/public/jobs?q=analyst")) == ["Data analyst"]
    assert titles(client.get("/api/public/jobs?q=dashboards")) == ["Data analyst"]
    assert titles(client.get("/api/public/jobs?q=brand")) == ["Designer"]
    assert titles(client.get("/api/public/jobs?q=plumber")) == []


def test_search_ignores_case_and_finds_other_forms_of_a_word(
    client: TestClient, db: Session, world: World
) -> None:
    open_job(world, db, title="Software Engineer", description="You will be building systems.")

    assert titles(client.get("/api/public/jobs?q=ENGINEERS")) == ["Software Engineer"]
    assert titles(client.get("/api/public/jobs?q=build")) == ["Software Engineer"]


def test_a_match_in_the_title_ranks_above_a_match_in_the_description(
    client: TestClient, db: Session, world: World
) -> None:
    now = datetime.now(UTC)
    open_job(
        world,
        db,
        title="Office manager",
        description="You will work next to our python developers.",
        opened_at=now,  # the newest, so only the ranking can put it second
    )
    open_job(
        world,
        db,
        title="Python developer",
        description="Write services.",
        opened_at=now - timedelta(days=30),
    )

    assert titles(client.get("/api/public/jobs?q=python")) == ["Python developer", "Office manager"]


def test_without_a_keyword_the_newest_opened_job_comes_first(
    client: TestClient, db: Session, world: World
) -> None:
    now = datetime.now(UTC)
    open_job(world, db, title="Oldest", opened_at=now - timedelta(days=9))
    open_job(world, db, title="Newest", opened_at=now)
    open_job(world, db, title="Middle", opened_at=now - timedelta(days=3))

    assert titles(client.get("/api/public/jobs")) == ["Newest", "Middle", "Oldest"]


def test_search_never_finds_text_of_jobs_that_are_not_open(
    client: TestClient, db: Session, world: World
) -> None:
    new_job(db, world, title="Confidential unicorn", status=PostingStatus.DRAFT)
    new_job(db, world, title="Retired unicorn", status=PostingStatus.CLOSED)
    db.commit()

    assert titles(client.get("/api/public/jobs?q=unicorn")) == []
    assert client.get("/api/public/jobs?q=unicorn").json()["total"] == 0


def test_search_phrases_and_exclusions_work_as_people_expect(
    client: TestClient, db: Session, world: World
) -> None:
    open_job(world, db, title="Senior backend engineer")
    open_job(world, db, title="Backend intern")

    assert titles(client.get('/api/public/jobs?q="backend engineer"')) == [
        "Senior backend engineer"
    ]
    assert titles(client.get("/api/public/jobs?q=backend -intern")) == ["Senior backend engineer"]
    assert sorted(titles(client.get("/api/public/jobs?q=engineer OR intern"))) == [
        "Backend intern",
        "Senior backend engineer",
    ]


@pytest.mark.parametrize(
    "hostile",
    [
        "'; DROP TABLE jobs; --",
        "&|!():*<>",
        "\\",
        '"',
        '"unbalanced',
        "a" * 200,
        "%_",
        "\u0000",
        "the",  # only a stop word: valid, but matches nothing
    ],
)
def test_odd_search_text_is_harmless(
    client: TestClient, db: Session, world: World, hostile: str
) -> None:
    open_job(world, db)

    response = client.get("/api/public/jobs", params={"q": hostile})

    assert response.status_code in (200, 422)  # a refusal is fine; a crash never is
    if response.status_code == 200:
        assert response.json()["total"] in (0, 1)
    # the table is still there
    assert client.get("/api/public/jobs").json()["total"] == 1


def test_a_blank_keyword_means_no_filter(client: TestClient, db: Session, world: World) -> None:
    open_job(world, db, title="Anything")

    assert titles(client.get("/api/public/jobs?q=")) == ["Anything"]
    assert titles(client.get("/api/public/jobs?q=%20%20")) == ["Anything"]


def test_a_keyword_longer_than_the_limit_is_refused(client: TestClient) -> None:
    assert client.get("/api/public/jobs", params={"q": "x" * 200}).status_code == 200
    assert client.get("/api/public/jobs", params={"q": "x" * 201}).status_code == 422


# ---- filters -----------------------------------------------------------------------------


def test_location_matches_part_of_the_text_ignoring_case(
    client: TestClient, db: Session, world: World
) -> None:
    open_job(world, db, title="In Oslo", location="Oslo, Norway")
    open_job(world, db, title="Remote one", location="Remote (EU)")

    assert titles(client.get("/api/public/jobs?location=norway")) == ["In Oslo"]
    assert titles(client.get("/api/public/jobs?location=REMOTE")) == ["Remote one"]


def test_location_wildcards_are_plain_characters(
    client: TestClient, db: Session, world: World
) -> None:
    open_job(world, db, title="In Oslo", location="Oslo")

    assert titles(client.get("/api/public/jobs", params={"location": "%"})) == []
    assert titles(client.get("/api/public/jobs", params={"location": "O_lo"})) == []


def test_the_company_filter_narrows_the_list(client: TestClient, db: Session, world: World) -> None:
    open_job(world, db, title="Acme job")
    open_job(world, db, company="globex", title="Globex job")

    assert titles(client.get(f"/api/public/jobs?company_id={world.globex.id}")) == ["Globex job"]
    assert titles(client.get(f"/api/public/jobs?company_id={uuid.uuid4()}")) == []
    assert client.get("/api/public/jobs?company_id=not-an-id").status_code == 422


def test_filters_and_keyword_combine(client: TestClient, db: Session, world: World) -> None:
    open_job(world, db, title="Engineer", location="Oslo")
    open_job(world, db, title="Engineer", location="Lisbon")
    open_job(world, db, title="Designer", location="Oslo")

    assert titles(client.get("/api/public/jobs?q=engineer&location=oslo")) == ["Engineer"]
    assert client.get("/api/public/jobs?q=engineer&location=oslo").json()["total"] == 1


# ---- paging ------------------------------------------------------------------------------


def test_the_list_is_paginated(client: TestClient, db: Session, world: World) -> None:
    now = datetime.now(UTC)
    for n in range(5):
        open_job(world, db, title=f"Job {n}", opened_at=now - timedelta(days=n))

    first = client.get("/api/public/jobs?page=1&page_size=2").json()
    last = client.get("/api/public/jobs?page=3&page_size=2").json()
    beyond = client.get("/api/public/jobs?page=4&page_size=2").json()

    assert [i["title"] for i in first["items"]] == ["Job 0", "Job 1"]
    assert [i["title"] for i in last["items"]] == ["Job 4"]
    assert beyond["items"] == [] and beyond["total"] == 5


@pytest.mark.parametrize("query", ["page=0", "page=10001", "page_size=0", "page_size=101"])
def test_silly_page_numbers_are_refused(client: TestClient, query: str) -> None:
    assert client.get(f"/api/public/jobs?{query}").status_code == 422


def test_a_search_is_paginated_too(client: TestClient, db: Session, world: World) -> None:
    for n in range(3):
        open_job(world, db, title=f"Engineer {n}")
    open_job(world, db, title="Cook")

    page = client.get("/api/public/jobs?q=engineer&page_size=2&page=2").json()

    assert page["total"] == 3 and len(page["items"]) == 1


# ---- cost --------------------------------------------------------------------------------


def test_the_list_costs_the_same_number_of_queries_however_many_jobs_there_are(
    client: TestClient, db: Session, scratch_engine: Engine, world: World
) -> None:
    counter = {"queries": 0}

    def count(*_args: object) -> None:
        counter["queries"] += 1

    def queries_for_one_request() -> int:
        counter["queries"] = 0
        event.listen(scratch_engine, "before_cursor_execute", count)
        try:
            assert client.get("/api/public/jobs?q=engineer&page_size=100").status_code == 200
        finally:
            event.remove(scratch_engine, "before_cursor_execute", count)
        return counter["queries"]

    for n in range(3):
        open_job(world, db, title=f"Engineer A{n}")
    few = queries_for_one_request()
    for n in range(30):
        open_job(world, db, company="globex", title=f"Engineer B{n}")
    many = queries_for_one_request()

    assert few == many


def test_the_search_column_has_an_index_the_keyword_query_can_use(
    db: Session, world: World
) -> None:
    # With few rows Postgres rightly prefers a plain scan, so forbid that to prove the index fits
    # the query form the endpoint uses (a GIN index on the generated column).
    db.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        row[0]
        for row in db.execute(
            text(
                "EXPLAIN SELECT id FROM jobs "
                "WHERE search_vector @@ websearch_to_tsquery('english', 'engineer')"
            )
        )
    )
    db.rollback()

    assert "ix_jobs_search_vector" in plan
