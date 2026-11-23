"""Signing in with Google (functional.md > Sign in with Google and link accounts).

The rules under test, in the order they matter most:

* An account is only ever linked to a Google identity when Google says the email is verified AND the
  existing account's email is verified too; otherwise the person is told to log in with their
  password first and nothing is linked.
* Google never grants a role: a person who signs in gets the role they already have, and an unknown
  email always becomes a candidate.
* A deactivated or anonymized account cannot sign in this way.
* The way back is protected against login-CSRF by a signed state PLUS a cookie only this browser
  has, and only ever redirects to fixed addresses of ours.
* Google's own words, codes and tokens never reach a log, an answer or an address.

Google is the fake in `tests/fake_google.py`: no test reaches the real one.
"""

import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.auth import tokens
from app.auth.sessions import SESSION_COOKIE_NAME
from app.models import AuditLog, CandidateProfile, ExternalIdentity, Role, User
from app.services import google_login
from app.services.google_login import GoogleLoginError
from tests.conftest import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from tests.factories import make_candidate, make_company, make_user
from tests.fake_google import FakeGoogle, make_id_token

NONCE_COOKIE = "ats_google_nonce"
START = "/api/auth/google/start"
CALLBACK = "/api/auth/google/callback"


def start(client: TestClient) -> str:
    """Press "Continue with Google": returns the state Google will send back."""
    client.cookies.clear()
    response = client.get(START, follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/")
    return parse_qs(urlsplit(location).query)["state"][0]


def come_back(client: TestClient, **params: str) -> Response:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return client.get(f"{CALLBACK}?{query}", follow_redirects=False)


def sign_in(
    client: TestClient, fake: FakeGoogle, *, code: str = "the-code", **identity: object
) -> Response:
    """The whole round trip: press the button, sign in at Google, come back."""
    state = start(client)
    fake.grant_login_code(code, **identity)  # type: ignore[arg-type]
    return come_back(client, code=code, state=state)


def refused_with(response: Response, reason: str) -> None:
    assert response.status_code == 303
    assert response.headers["location"] == f"/login?google_error={reason}"
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")


def signed_in(response: Response) -> None:
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert f"{SESSION_COOKIE_NAME}=" in response.headers.get("set-cookie", "")


def users_with_email(db: Session, email: str) -> list[User]:
    db.expire_all()
    return list(db.scalars(select(User).where(func.lower(User.email) == email.lower())))


def identities(db: Session) -> list[ExternalIdentity]:
    db.expire_all()
    return list(db.scalars(select(ExternalIdentity)))


# ---- the button and the way there ---------------------------------------------------------------


def test_the_button_is_offered_only_when_google_is_set_up(
    client: TestClient, fake_google: FakeGoogle, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get("/api/auth/google/config").json() == {"enabled": True}

    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY")
    assert client.get("/api/auth/google/config").json() == {"enabled": False}


def test_starting_sends_the_browser_to_google_asking_only_who_they_are(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    response = client.get(START, follow_redirects=False)

    assert response.status_code == 303
    parts = urlsplit(response.headers["location"])
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query["client_id"] == GOOGLE_CLIENT_ID
    assert query["redirect_uri"] == "https://ats.test/api/auth/google/callback"
    assert query["response_type"] == "code"
    # Who they are, and nothing else: no calendar, no offline access, no stored token.
    assert set(query["scope"].split()) == {"openid", "email", "profile"}
    assert "access_type" not in query
    assert query["prompt"] == "select_account"
    assert query["state"]


def test_starting_gives_this_browser_a_short_lived_private_cookie(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    response = client.get(START, follow_redirects=False)

    cookie = next(
        value for value in response.headers.get_list("set-cookie") if NONCE_COOKIE in value
    ).lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "path=/api/auth/google" in cookie
    assert "max-age=600;" in cookie  # exactly ten minutes, not merely starting with 600


def test_starting_without_google_set_up_says_so_and_sets_nothing(client: TestClient) -> None:
    response = client.get(START, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?google_error=not_configured"
    # At most a cookie being deleted: never one that is set.
    for value in response.headers.get_list("set-cookie"):
        assert NONCE_COOKIE not in value or "max-age=0" in value.lower()


def test_coming_back_without_google_set_up_says_so(client: TestClient) -> None:
    refused_with(come_back(client, code="x", state="y"), "not_configured")


# ---- a new person ------------------------------------------------------------------------------


def test_an_unknown_email_becomes_a_verified_candidate_with_no_password(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    response = sign_in(client, fake_google, email="New.Person@Example.test", name="New Person")

    signed_in(response)
    [user] = users_with_email(db, "new.person@example.test")
    assert user.role == Role.CANDIDATE
    assert user.company_id is None
    assert user.full_name == "New Person"
    assert user.email == "new.person@example.test"  # stored the way every email is: lowercase
    assert user.email_verified_at is not None  # Google vouched for it
    assert user.password_hash is None
    assert user.last_login_at is not None
    assert db.get(CandidateProfile, user.id) is not None
    [identity] = identities(db)
    assert (identity.user_id, identity.provider, identity.subject) == (
        user.id,
        "google",
        "google-sub-1",
    )
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "account.google_created")).all()
    assert [row.entity_id for row in audit] == [user.id]
    # And the cookie really is a working session for them.
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "new.person@example.test"


def test_a_name_is_made_from_the_email_when_google_sends_none(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    sign_in(client, fake_google, email="quiet.one@example.test", name=None)

    [user] = users_with_email(db, "quiet.one@example.test")
    assert user.full_name == "quiet.one"


def test_a_very_long_name_from_google_is_cut_to_fit_rather_than_failing(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    signed_in(sign_in(client, fake_google, email="long@example.test", name="N" * 500))

    [user] = users_with_email(db, "long@example.test")
    assert user.full_name == "N" * 200


def test_google_never_creates_a_staff_account(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    # Even an address that looks like a company's: an unknown email is a candidate, full stop.
    make_company(db, "Acme")
    db.commit()

    sign_in(client, fake_google, email="someone@acme.test")

    [user] = users_with_email(db, "someone@acme.test")
    assert (user.role, user.company_id) == (Role.CANDIDATE, None)


def test_a_google_created_account_cannot_log_in_with_a_password(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    sign_in(client, fake_google, email="new.person@example.test")
    client.cookies.clear()

    for password in ("", "anything at all 123", "None"):
        response = client.post(
            "/api/auth/login", json={"email": "new.person@example.test", "password": password}
        )
        assert response.status_code in (401, 422)


# ---- coming back again -------------------------------------------------------------------------


def test_the_second_sign_in_finds_the_person_by_their_google_id_even_if_the_email_changed(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    sign_in(client, fake_google, subject="stable-id", email="before@example.test")

    response = sign_in(
        client, fake_google, code="second", subject="stable-id", email="after@example.test"
    )

    signed_in(response)
    db.expire_all()
    [user] = db.scalars(select(User)).all()
    assert user.email == "before@example.test"  # our record does not change by itself
    assert len(identities(db)) == 1


def test_signing_in_does_not_write_an_audit_row_each_time(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    sign_in(client, fake_google)
    sign_in(client, fake_google, code="second")
    sign_in(client, fake_google, code="third")

    db.expire_all()
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 1  # the creation only


# ---- linking to an existing account ------------------------------------------------------------


def test_a_verified_candidate_with_the_same_email_is_linked_and_keeps_their_password(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    cara = make_candidate(db, email="cara@example.test", resume=False)
    cara.password_hash = "kept-as-it-was"
    db.commit()

    response = sign_in(client, fake_google, email="CARA@example.test", name="Someone Else")

    signed_in(response)
    db.expire_all()
    assert len(db.scalars(select(User)).all()) == 1  # no second account
    refreshed = db.get(User, cara.id)
    assert refreshed is not None
    assert refreshed.password_hash == "kept-as-it-was"
    assert refreshed.full_name == "Test Candidate"  # Google does not rename them
    [identity] = identities(db)
    assert identity.user_id == cara.id
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "account.google_linked")).all()
    assert [row.entity_id for row in audit] == [cara.id]
    assert client.get("/api/auth/me").json()["user"]["id"] == str(cara.id)


@pytest.mark.parametrize("role", [Role.RECRUITER, Role.COMPANY_ADMIN, Role.INTERVIEWER])
def test_a_verified_staff_member_is_linked_and_keeps_their_role_and_company(
    client: TestClient, db: Session, fake_google: FakeGoogle, role: Role
) -> None:
    company = make_company(db, "Acme")
    staff = make_user(db, email="staff@acme.test", role=role, company=company)
    db.commit()

    response = sign_in(client, fake_google, email="staff@acme.test")

    signed_in(response)
    me = client.get("/api/auth/me").json()["user"]
    assert (me["id"], me["role"], me["company_id"]) == (str(staff.id), role.value, str(company.id))
    [identity] = identities(db)
    assert identity.user_id == staff.id


def test_an_account_whose_email_is_not_verified_yet_is_not_linked(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    # An invited interviewer who never confirmed their address, and a candidate who never did.
    company = make_company(db, "Acme")
    make_user(db, email="ian@acme.test", role=Role.INTERVIEWER, company=company, verified=False)
    make_candidate(db, email="dee@example.test", resume=False, verified=False)
    db.commit()

    for email in ("ian@acme.test", "dee@example.test"):
        refused_with(sign_in(client, fake_google, email=email), "account_unverified")

    assert identities(db) == []


@pytest.mark.parametrize("claim", [False, "false"])
def test_google_saying_the_email_is_not_verified_links_nothing_even_to_a_verified_account(
    client: TestClient, db: Session, fake_google: FakeGoogle, claim: bool | str
) -> None:
    make_candidate(db, email="cara@example.test", resume=False)
    db.commit()

    refused_with(
        sign_in(client, fake_google, email="cara@example.test", email_verified=claim),
        "email_not_verified",
    )

    assert identities(db) == []


def test_google_saying_the_email_is_not_verified_creates_no_account(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    refused_with(
        sign_in(client, fake_google, email="new@example.test", email_verified=False),
        "email_not_verified",
    )

    assert users_with_email(db, "new@example.test") == []


def test_google_saying_true_as_a_word_is_accepted(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    # Google has been seen to send the claim as the string "true".
    signed_in(sign_in(client, fake_google, email="new@example.test", email_verified="true"))


def test_a_google_id_already_linked_to_someone_else_cannot_be_used_for_a_second_account(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    first = make_candidate(db, email="first@example.test", resume=False)
    second = make_candidate(db, email="second@example.test", resume=False)
    db.commit()
    sign_in(client, fake_google, subject="one-google-account", email="first@example.test")

    # The same Google account, now claiming the other address: it is still the first person.
    sign_in(
        client,
        fake_google,
        code="again",
        subject="one-google-account",
        email="second@example.test",
    )

    assert client.get("/api/auth/me").json()["user"]["id"] == str(first.id)
    assert [identity.user_id for identity in identities(db)] == [first.id]
    assert second.id not in [identity.user_id for identity in identities(db)]


# ---- people who may not sign in ----------------------------------------------------------------


def test_a_deactivated_account_cannot_sign_in_by_email_or_by_google_id(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    cara = make_candidate(db, email="cara@example.test", resume=False)
    db.commit()
    signed_in(sign_in(client, fake_google, email="cara@example.test"))  # linked while active
    cara.is_active = False
    cara.deactivated_at = datetime.now(UTC)
    db.commit()

    by_id = sign_in(client, fake_google, code="by-id", email="cara@example.test")
    refused_with(by_id, "account_unavailable")

    other = make_candidate(db, email="other@example.test", resume=False)
    other.is_active = False
    db.commit()
    by_email = sign_in(
        client,
        fake_google,
        code="by-email",
        subject="another-google-id",
        email="other@example.test",
    )
    refused_with(by_email, "account_unavailable")
    assert len(identities(db)) == 1  # nothing new was linked


def test_an_anonymized_account_cannot_sign_in(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    gone = make_candidate(db, email="gone@example.test", resume=False)
    gone.anonymized_at = datetime.now(UTC)
    db.commit()

    refused_with(sign_in(client, fake_google, email="gone@example.test"), "account_unavailable")

    assert identities(db) == []


# ---- the way back is protected -----------------------------------------------------------------


def test_a_code_and_state_from_someone_elses_browser_do_not_log_this_browser_in(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    # Login-CSRF: an attacker starts a sign-in, then gets the victim's browser to open the way back.
    state = start(client)
    fake_google.grant_login_code("attackers-code", email="attacker@example.test")
    client.cookies.clear()  # the victim's browser never had the attacker's cookie

    refused_with(come_back(client, code="attackers-code", state=state), "bad_state")

    assert users_with_email(db, "attacker@example.test") == []
    assert "attackers-code" in fake_google.login_codes  # Google was never even asked


def test_a_cookie_from_another_sign_in_does_not_match_this_state(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    state = start(client)
    client.cookies.set(NONCE_COOKIE, str(uuid.uuid4()), path="/api/auth/google")
    fake_google.grant_login_code("code")

    refused_with(come_back(client, code="code", state=state), "bad_state")


@pytest.mark.parametrize("state", ["", "garbage", "a.b.c", "x" * 500])
def test_a_garbled_state_is_refused(
    client: TestClient, fake_google: FakeGoogle, state: str
) -> None:
    start(client)
    fake_google.grant_login_code("code")

    refused_with(come_back(client, code="code", state=state), "bad_state")


def test_a_tampered_state_is_refused(client: TestClient, fake_google: FakeGoogle) -> None:
    state = start(client)
    fake_google.grant_login_code("code")
    tampered = state[:-1] + ("0" if state[-1] != "0" else "1")

    refused_with(come_back(client, code="code", state=tampered), "bad_state")


def test_a_state_older_than_ten_minutes_is_refused(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    nonce = uuid.uuid4()
    old = tokens.make_state(tokens.GOOGLE_LOGIN, nonce, datetime.now(UTC) - timedelta(minutes=11))
    client.cookies.set(NONCE_COOKIE, str(nonce), path="/api/auth/google")
    fake_google.grant_login_code("code")

    refused_with(come_back(client, code="code", state=old), "bad_state")


def test_a_state_made_for_the_calendar_cannot_be_used_to_sign_in(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    nonce = uuid.uuid4()
    calendar_state = tokens.make_state(tokens.GOOGLE_CALENDAR, nonce, datetime.now(UTC))
    client.cookies.set(NONCE_COOKIE, str(nonce), path="/api/auth/google")
    fake_google.grant_login_code("code")

    refused_with(come_back(client, code="code", state=calendar_state), "bad_state")


def test_a_finished_sign_in_cannot_be_replayed(client: TestClient, fake_google: FakeGoogle) -> None:
    state = start(client)
    fake_google.grant_login_code("code")
    signed_in(come_back(client, code="code", state=state))
    client.cookies.clear()

    fake_google.grant_login_code("code-2")
    refused_with(come_back(client, code="code-2", state=state), "bad_state")


def test_the_cookie_is_cleared_when_the_person_comes_back_either_way(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    state = start(client)
    fake_google.grant_login_code("code")

    good = come_back(client, code="code", state=state)
    bad = come_back(client, code="code", state="garbage")

    for response in (good, bad):
        cleared = [
            value for value in response.headers.get_list("set-cookie") if NONCE_COOKIE in value
        ]
        assert cleared, "the nonce cookie must be deleted"
        assert "max-age=0" in cleared[0].lower() or "1970" in cleared[0]


def test_the_way_back_only_ever_redirects_to_our_own_fixed_addresses(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    state = start(client)
    fake_google.grant_login_code("code")

    response = come_back(
        client, code="code", state=state, next="https://evil.example", redirect="//evil.example"
    )

    assert response.headers["location"] == "/"


# ---- Google says no, or cannot be reached ------------------------------------------------------


def test_the_person_saying_no_in_googles_window_is_a_quiet_refusal(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    state = start(client)

    refused_with(come_back(client, error="access_denied", state=state), "access_denied")


def test_any_other_error_from_google_is_shown_as_a_general_one_never_in_googles_words(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    state = start(client)

    response = come_back(client, error="Something<script>", state=state)

    refused_with(response, "google_error")
    assert "script" not in response.headers["location"]


def test_coming_back_without_a_code_is_refused(client: TestClient, fake_google: FakeGoogle) -> None:
    state = start(client)

    refused_with(come_back(client, state=state), "missing_code")
    assert fake_google.calls == []


def test_google_being_down_is_told_plainly_and_creates_nothing(
    client: TestClient, db: Session, fake_google: FakeGoogle
) -> None:
    state = start(client)
    fake_google.grant_login_code("code")
    fake_google.fail_next(status=503)

    refused_with(come_back(client, code="code", state=state), "google_unavailable")

    assert db.scalars(select(User)).all() == []


def test_google_refusing_the_code_is_told_plainly(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    state = start(client)  # the code was never granted, so Google answers invalid_grant

    refused_with(come_back(client, code="unknown", state=state), "google_refused")


def test_a_code_works_only_once(client: TestClient, fake_google: FakeGoogle) -> None:
    state = start(client)
    fake_google.grant_login_code("code")
    signed_in(come_back(client, code="code", state=state))

    state = start(client)
    refused_with(come_back(client, code="code", state=state), "google_refused")


def _bad_tokens() -> dict[str, dict[str, object]]:
    return {
        "another app's audience": {"audience": "someone-elses-client.apps.googleusercontent.com"},
        "another issuer": {"issuer": "https://evil.example"},
        "expired": {"expires_in": -10},
        "no subject": {"subject": ""},
        "no email": {"email": ""},
        "not a token at all": {"id_token": "not-a-token"},
        "not json inside": {"id_token": "aaa.bbbb.ccc"},
    }


@pytest.mark.parametrize("what", list(_bad_tokens()))
def test_an_id_token_that_is_not_for_us_or_not_valid_is_refused(
    client: TestClient, db: Session, fake_google: FakeGoogle, what: str
) -> None:
    response = sign_in(client, fake_google, **_bad_tokens()[what])

    refused_with(response, "google_refused")
    assert db.scalars(select(User)).all() == []


def test_a_token_without_the_expiry_claim_is_refused(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    state = start(client)
    fake_google.login_codes["code"] = make_id_token(
        {
            "iss": "https://accounts.google.com",
            "aud": GOOGLE_CLIENT_ID,
            "sub": "s",
            "email": "a@example.test",
            "email_verified": True,
        }
    )

    refused_with(come_back(client, code="code", state=state), "google_refused")


def test_either_form_of_googles_issuer_is_accepted(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    signed_in(sign_in(client, fake_google, issuer="accounts.google.com"))


def test_an_audience_list_that_includes_us_is_accepted(
    client: TestClient, fake_google: FakeGoogle
) -> None:
    state = start(client)
    fake_google.login_codes["code"] = make_id_token(
        {
            "iss": "https://accounts.google.com",
            "aud": [GOOGLE_CLIENT_ID, "another"],
            "sub": "s",
            "email": "a@example.test",
            "email_verified": True,
            "exp": 4_000_000_000,
        }
    )

    signed_in(come_back(client, code="code", state=state))


# ---- what must never leak ----------------------------------------------------------------------


def test_no_code_token_or_secret_reaches_a_log_or_an_answer(
    client: TestClient, fake_google: FakeGoogle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    state = start(client)
    fake_google.grant_login_code("secret-looking-code-123", email="leak.check@example.test")
    ok = come_back(client, code="secret-looking-code-123", state=state)
    state = start(client)
    fake_google.fail_next(status=503)
    down = come_back(client, code="secret-looking-code-456", state=state)

    # The test client (httpx) logs the addresses it requests: that is the test's own noise, not the
    # app. What the app logs is what must stay clean.
    app_logs = " ".join(
        record.getMessage() + str(record.__dict__)
        for record in caplog.records
        if not record.name.startswith("httpx")
    )
    everything = app_logs + ok.text + down.text + str(ok.headers) + str(down.headers)
    for secret in (
        "secret-looking-code-123",
        "secret-looking-code-456",
        GOOGLE_CLIENT_SECRET,
        "login-access-token",
        "not-a-real-signature",
    ):
        assert secret not in everything
    assert "leak.check@example.test" not in app_logs  # nor the person's address in the logs


# ---- two first sign-ins at once ----------------------------------------------------------------


def test_two_simultaneous_first_sign_ins_make_one_account(
    scratch_engine: Engine, fake_google: FakeGoogle
) -> None:
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def one_browser(code: str) -> None:
        with Session(scratch_engine) as session:
            now = datetime.now(UTC)
            url, nonce = google_login.start_login(now)
            state = parse_qs(urlsplit(url).query)["state"][0]
            fake_google.grant_login_code(code, subject="same-person", email="race@example.test")
            barrier.wait(timeout=10)
            try:
                google_login.finish_login(
                    session, now, code=code, state=state, error=None, nonce=nonce
                )
                session.commit()
                result = "signed in"
            except GoogleLoginError as failure:
                session.rollback()
                result = failure.reason
            with lock:
                outcomes.append(result)

    threads = [threading.Thread(target=one_browser, args=(f"code-{n}",)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    # One wins. The other either also signs in (it ran after the commit and found the person) or is
    # told to try again: never a crash, never two accounts.
    assert "signed in" in outcomes
    assert set(outcomes) <= {"signed in", "try_again"}
    with Session(scratch_engine) as check:
        assert len(check.scalars(select(User)).all()) == 1
        assert len(check.scalars(select(ExternalIdentity)).all()) == 1
