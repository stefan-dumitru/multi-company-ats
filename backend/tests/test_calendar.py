"""Connecting and disconnecting a Google account (functional.md > Schedule an interview).

The rules under test: only recruiters connect; the way back from Google is protected by a signed,
recent `state` made for the person who is logged in; the refresh token is stored encrypted and never
appears in a log or a response; nothing Google does can break the app; and disconnecting always
leaves the person disconnected, even if Google cannot be reached.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import tokens
from app.models import AuditLog, GoogleCalendarConnection, Role, User
from tests.browser import Browser
from tests.conftest import GOOGLE_CLIENT_SECRET
from tests.factories import make_candidate, make_company, make_user
from tests.fake_google import FakeGoogle

STATUS_FIELDS = {"configured", "connected", "connected_at"}


@dataclass
class World:
    recruiter: User
    other_recruiter: User
    admin: User
    interviewer: User
    cara: User


@pytest.fixture
def world(db: Session) -> World:
    company = make_company(db, "Acme")
    built = World(
        recruiter=make_user(db, email="rec@acme.test", role=Role.RECRUITER, company=company),
        other_recruiter=make_user(db, email="rec2@acme.test", role=Role.RECRUITER, company=company),
        admin=make_user(db, email="admin@acme.test", role=Role.COMPANY_ADMIN, company=company),
        interviewer=make_user(db, email="int@acme.test", role=Role.INTERVIEWER, company=company),
        cara=make_candidate(db, email="cara@example.test"),
    )
    db.commit()
    return built


def connect_url(browser: Browser) -> str:
    response = browser.send("POST", "/api/calendar/connect")
    assert response.status_code == 200
    return str(response.json()["url"])


def state_of(url: str) -> str:
    return parse_qs(urlsplit(url).query)["state"][0]


def come_back(browser: Browser, **params: str) -> Response:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return browser.client.get(f"/api/calendar/callback?{query}", follow_redirects=False)


def connect_fully(
    browser: Browser, fake: FakeGoogle, *, code: str = "the-code", refresh: str = "refresh-1"
) -> Response:
    """The whole round trip: start, agree in Google's window, come back."""
    state = state_of(connect_url(browser))
    fake.grant_code(code, refresh_token=refresh)
    return come_back(browser, code=code, state=state)


def connections(db: Session) -> list[GoogleCalendarConnection]:
    db.expire_all()
    return list(db.scalars(select(GoogleCalendarConnection)))


def audit_actions(db: Session) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.created_at, AuditLog.id)))


# ---- status ------------------------------------------------------------------------------------


def test_a_server_without_google_settings_says_so_and_nothing_breaks(
    client: TestClient, db: Session, world: World
) -> None:
    browser = Browser(client, db, world.recruiter)

    status = browser.get("/api/calendar")
    connect = browser.send("POST", "/api/calendar/connect")

    assert status.status_code == 200
    assert status.json() == {"configured": False, "connected": False, "connected_at": None}
    assert connect.status_code == 503 and connect.json()["code"] == "calendar_not_configured"


def test_a_recruiter_who_has_not_connected_sees_that(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    body = Browser(client, db, world.recruiter).get("/api/calendar").json()

    assert set(body) == STATUS_FIELDS
    assert body == {"configured": True, "connected": False, "connected_at": None}


def test_a_connected_recruiter_sees_since_when(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    connect_fully(browser, fake_google)

    body = browser.get("/api/calendar").json()

    assert body["configured"] is True and body["connected"] is True
    assert datetime.fromisoformat(body["connected_at"]).tzinfo is not None


def test_each_recruiter_sees_only_their_own_connection(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect_fully(Browser(client, db, world.recruiter), fake_google)

    other = Browser(client, db, world.other_recruiter).get("/api/calendar").json()

    assert other["connected"] is False


# ---- starting ----------------------------------------------------------------------------------


def test_starting_gives_the_address_of_googles_window_with_a_state_for_this_person(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    url = connect_url(Browser(client, db, world.recruiter))

    assert url.startswith("https://accounts.google.com/")
    owner = tokens.read_state(
        tokens.GOOGLE_CALENDAR, state_of(url), datetime.now(UTC), timedelta(minutes=10)
    )
    assert owner == world.recruiter.id
    assert GOOGLE_CLIENT_SECRET not in url


def test_starting_needs_the_csrf_header_like_every_change(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    Browser(client, db, world.recruiter)  # logged in, but this request carries no CSRF header

    assert client.post("/api/calendar/connect").status_code == 403


# ---- coming back from Google -------------------------------------------------------------------


def test_coming_back_connects_and_sends_the_person_to_the_calendar_page(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    response = connect_fully(Browser(client, db, world.recruiter), fake_google)

    assert response.status_code == 303 and response.headers["location"] == "/calendar?connected=1"
    stored = connections(db)
    assert len(stored) == 1 and stored[0].user_id == world.recruiter.id
    assert "calendar.events" in stored[0].scopes
    exchange = fake_google.calls[0].form
    assert exchange["code"] == "the-code"
    assert exchange["redirect_uri"] == "https://ats.test/api/calendar/callback"
    assert audit_actions(db) == ["calendar.connected"]


def test_the_refresh_token_is_stored_encrypted_and_only_the_key_opens_it(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle, google_env: str
) -> None:
    connect_fully(Browser(client, db, world.recruiter), fake_google, refresh="plain-refresh-token")

    stored = connections(db)[0].refresh_token_encrypted
    raw = db.execute(
        text("select refresh_token_encrypted from google_calendar_connections")
    ).scalar()
    assert raw == stored and "plain-refresh-token" not in stored
    assert Fernet(google_env.encode()).decrypt(stored.encode()) == b"plain-refresh-token"
    assert "plain-refresh-token" not in str(audit_actions(db))


def test_connecting_again_replaces_the_token_and_keeps_one_row(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle, google_env: str
) -> None:
    browser = Browser(client, db, world.recruiter)
    connect_fully(browser, fake_google, code="c1", refresh="first-token")
    connect_fully(browser, fake_google, code="c2", refresh="second-token")

    stored = connections(db)

    assert len(stored) == 1
    assert (
        Fernet(google_env.encode()).decrypt(stored[0].refresh_token_encrypted.encode())
        == b"second-token"
    )


@pytest.mark.parametrize("kind", ["tampered", "expired", "someone_elses", "missing", "garbage"])
def test_a_bad_state_connects_nobody_and_never_reaches_google(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle, kind: str
) -> None:
    browser = Browser(client, db, world.recruiter)
    good = state_of(connect_url(browser))
    states = {
        "tampered": good[:-1] + ("0" if good[-1] != "0" else "1"),
        "expired": tokens.make_state(
            tokens.GOOGLE_CALENDAR, world.recruiter.id, datetime.now(UTC) - timedelta(hours=1)
        ),
        "someone_elses": tokens.make_state(
            tokens.GOOGLE_CALENDAR, world.other_recruiter.id, datetime.now(UTC)
        ),
        "garbage": "not-a-state",
    }
    fake_google.grant_code("the-code")
    params = (
        {"code": "the-code"} if kind == "missing" else {"code": "the-code", "state": states[kind]}
    )

    response = come_back(browser, **params)

    assert (
        response.status_code == 303 and response.headers["location"] == "/calendar?error=bad_state"
    )
    assert connections(db) == [] and fake_google.calls == []


def test_a_state_cannot_be_replayed_by_someone_else_who_is_logged_in(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    # A link made for Rec1 is followed by Rec2, who is logged in: Rec2 must not get Rec1's.
    state = state_of(connect_url(Browser(client, db, world.recruiter)))
    fake_google.grant_code("the-code")

    response = come_back(Browser(client, db, world.other_recruiter), code="the-code", state=state)

    assert response.headers["location"] == "/calendar?error=bad_state"
    assert connections(db) == []


def test_saying_no_in_googles_window_is_a_friendly_outcome(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    state = state_of(connect_url(browser))

    response = come_back(browser, error="access_denied", state=state)

    assert response.headers["location"] == "/calendar?error=access_denied"
    assert connections(db) == [] and fake_google.calls == []


def test_a_return_with_neither_code_nor_error_is_refused(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    state = state_of(connect_url(browser))

    response = come_back(browser, state=state)

    assert response.headers["location"] == "/calendar?error=missing_code"
    assert connections(db) == []


def test_google_being_down_on_the_way_back_is_reported_not_raised(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    state = state_of(connect_url(browser))
    fake_google.fail_next(status=503)

    response = come_back(browser, code="c", state=state)

    assert response.status_code == 303
    assert response.headers["location"] == "/calendar?error=google_unavailable"
    assert connections(db) == []


def test_google_refusing_the_code_is_reported(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    state = state_of(connect_url(browser))

    response = come_back(browser, code="a-code-google-never-issued", state=state)

    assert response.headers["location"] == "/calendar?error=google_refused"
    assert connections(db) == []


def test_an_answer_without_a_refresh_token_connects_nobody(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    state = state_of(connect_url(browser))
    fake_google.grant_code("the-code", refresh_token=None)

    response = come_back(browser, code="the-code", state=state)

    assert response.headers["location"] == "/calendar?error=google_refused"
    assert connections(db) == []


def test_coming_back_to_a_server_without_google_settings_says_so(
    client: TestClient, db: Session, world: World
) -> None:
    response = come_back(Browser(client, db, world.recruiter), code="c", state="s")

    assert response.headers["location"] == "/calendar?error=not_configured"


# ---- disconnecting -----------------------------------------------------------------------------


def test_disconnecting_revokes_at_google_and_forgets_the_token(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    connect_fully(browser, fake_google, refresh="refresh-to-revoke")

    response = browser.send("DELETE", "/api/calendar/connection")

    assert response.status_code == 204
    assert connections(db) == [] and fake_google.revoked == ["refresh-to-revoke"]
    assert browser.get("/api/calendar").json()["connected"] is False
    assert audit_actions(db) == ["calendar.connected", "calendar.disconnected"]


def test_disconnecting_still_disconnects_when_google_cannot_be_reached(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    browser = Browser(client, db, world.recruiter)
    connect_fully(browser, fake_google)
    fake_google.fail_next(raises=OSError("down"))

    response = browser.send("DELETE", "/api/calendar/connection")

    assert response.status_code == 204 and connections(db) == []


def test_disconnecting_when_not_connected_changes_nothing(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    response = Browser(client, db, world.recruiter).send("DELETE", "/api/calendar/connection")

    assert response.status_code == 204
    assert fake_google.calls == [] and audit_actions(db) == []


def test_disconnecting_one_recruiter_leaves_another_connected(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    connect_fully(Browser(client, db, world.other_recruiter), fake_google, code="c2", refresh="r2")
    mine = Browser(client, db, world.recruiter)
    connect_fully(mine, fake_google, code="c1", refresh="r1")

    mine.send("DELETE", "/api/calendar/connection")

    assert [row.user_id for row in connections(db)] == [world.other_recruiter.id]


def test_disconnecting_works_even_if_the_server_lost_its_settings(
    client: TestClient,
    db: Session,
    world: World,
    fake_google: FakeGoogle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = Browser(client, db, world.recruiter)
    connect_fully(browser, fake_google)
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY"):
        monkeypatch.delenv(name)

    response = browser.send("DELETE", "/api/calendar/connection")

    assert response.status_code == 204 and connections(db) == []  # nothing to revoke with, but gone


# ---- who may do any of it ----------------------------------------------------------------------


@pytest.mark.parametrize("who", ["admin", "interviewer", "cara"])
def test_only_recruiters_have_a_calendar(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle, who: str
) -> None:
    browser = Browser(client, db, getattr(world, who))

    assert browser.get("/api/calendar").status_code == 403
    assert browser.send("POST", "/api/calendar/connect").status_code == 403
    assert come_back(browser, code="c", state="s").status_code == 403
    assert browser.send("DELETE", "/api/calendar/connection").status_code == 403


def test_a_visitor_is_not_logged_in(
    client: TestClient, db: Session, world: World, fake_google: FakeGoogle
) -> None:
    client.cookies.clear()

    assert client.get("/api/calendar").status_code == 401
    assert client.post("/api/calendar/connect").status_code == 401
    assert (
        client.get("/api/calendar/callback?code=c&state=s", follow_redirects=False).status_code
        == 401
    )
    assert client.delete("/api/calendar/connection").status_code == 401


# ---- nothing secret in logs or answers ---------------------------------------------------------


def test_no_token_code_or_secret_reaches_a_log_or_an_answer(
    client: TestClient,
    db: Session,
    world: World,
    fake_google: FakeGoogle,
    google_env: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    browser = Browser(client, db, world.recruiter)
    answers = []

    answers.append(browser.send("POST", "/api/calendar/connect").text)
    response = connect_fully(browser, fake_google, code="secret-code", refresh="secret-refresh")
    answers += [response.text, str(response.headers), browser.get("/api/calendar").text]
    fake_google.fail_next(status=503, body=b"secret-refresh secret-code")
    browser.send("DELETE", "/api/calendar/connection")
    answers.append(browser.get("/api/calendar").text)

    # The test client (httpx) logs the addresses it requests: that is the test's own noise, not
    # the app. What the app and its worker log is what must stay clean.
    app_logs = " ".join(
        record.getMessage() + str(record.__dict__)
        for record in caplog.records
        if not record.name.startswith("httpx")
    )
    everything = app_logs + " ".join(answers)
    for secret in ("secret-code", "secret-refresh", GOOGLE_CLIENT_SECRET, google_env):
        assert secret not in everything
