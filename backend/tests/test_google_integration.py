"""The one module that talks to Google (`app.integrations.google`), against the fake Google.

What it must get right: ask Google for exactly what we mean (the narrowest permission, a refresh
token every time, our signed `state`), use only https and short timeouts, tell "Google is down" from
"Google said no", and never put a token or secret into an error.
"""

from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import get_google_settings
from app.integrations import google
from tests.conftest import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from tests.fake_google import FakeGoogle


def settings() -> google.GoogleSettings:
    found = get_google_settings()
    assert found is not None
    return found


# ---- the address Google's window opens at ------------------------------------------------------


def test_the_authorization_address_asks_for_exactly_what_we_need(fake_google: FakeGoogle) -> None:
    url = google.authorization_url(settings(), "the-state")

    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == google.AUTH_URL
    assert query == {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": "https://ats.test/api/calendar/callback",
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar.events",  # the narrowest that works
        "access_type": "offline",  # we need to act when the person is not there
        "prompt": "consent",  # so Google always hands over a refresh token
        "state": "the-state",
        "include_granted_scopes": "false",
    }
    assert GOOGLE_CLIENT_SECRET not in url  # the secret never goes through the browser


# ---- exchanging the code -----------------------------------------------------------------------


def test_a_code_is_exchanged_for_a_refresh_token(fake_google: FakeGoogle) -> None:
    fake_google.grant_code("code-1", refresh_token="r-1", access_token="a-1")

    grant = google.exchange_code(settings(), "code-1")

    assert grant.refresh_token == "r-1" and grant.access_token == "a-1"
    assert grant.scope == google.SCOPE
    call = fake_google.calls[0]
    assert call.method == "POST" and call.url == google.TOKEN_URL
    assert call.form["code"] == "code-1" and call.form["grant_type"] == "authorization_code"


def test_an_answer_without_a_refresh_token_is_refused(fake_google: FakeGoogle) -> None:
    fake_google.grant_code("code-1", refresh_token=None)

    with pytest.raises(google.GoogleRefused) as raised:
        google.exchange_code(settings(), "code-1")

    assert raised.value.reason == "no_refresh_token"


def test_the_permission_must_cover_calendar_events(fake_google: FakeGoogle) -> None:
    # The person can untick what we asked for in Google's window.
    fake_google.grant_code("code-1", scope="openid email")

    with pytest.raises(google.GoogleRefused) as raised:
        google.exchange_code(settings(), "code-1")

    assert raised.value.reason == "missing_scope"


def test_a_code_works_once_only(fake_google: FakeGoogle) -> None:
    fake_google.grant_code("code-1")
    google.exchange_code(settings(), "code-1")

    with pytest.raises(google.GoogleRefused) as raised:
        google.exchange_code(settings(), "code-1")

    assert raised.value.reason == "invalid_grant"


# ---- refreshing and revoking -------------------------------------------------------------------


def test_a_refresh_token_gives_a_fresh_access_token(fake_google: FakeGoogle) -> None:
    fake_google.refresh_tokens.add("r-1")

    assert google.refresh_access_token(settings(), "r-1") == "fresh-access-token"
    assert fake_google.calls[0].form["grant_type"] == "refresh_token"


def test_a_token_the_person_revoked_is_a_refusal_with_a_reason(fake_google: FakeGoogle) -> None:
    with pytest.raises(google.GoogleRefused) as raised:
        google.refresh_access_token(settings(), "never-issued")

    assert raised.value.reason == "invalid_grant"


def test_revoking_asks_google_to_forget_the_token(fake_google: FakeGoogle) -> None:
    google.revoke(settings(), "r-1")

    assert fake_google.revoked == ["r-1"]
    assert fake_google.calls[0].url == google.REVOKE_URL


# ---- when Google is not behaving ---------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_server_error_is_google_being_unavailable(fake_google: FakeGoogle, status: int) -> None:
    fake_google.fail_next(status=status)

    with pytest.raises(google.GoogleUnavailable):
        google.refresh_access_token(settings(), "r-1")


@pytest.mark.parametrize("error", [OSError("no route"), TimeoutError("slow"), ConnectionError("x")])
def test_a_network_failure_is_google_being_unavailable(
    fake_google: FakeGoogle, error: Exception
) -> None:
    fake_google.fail_next(raises=error)

    with pytest.raises(google.GoogleUnavailable):
        google.exchange_code(settings(), "code-1")


def test_a_refusal_that_is_not_json_is_still_a_refusal(fake_google: FakeGoogle) -> None:
    fake_google.fail_next(status=400, body=b"<html>proxy error</html>")

    with pytest.raises(google.GoogleRefused) as raised:
        google.refresh_access_token(settings(), "r-1")

    assert raised.value.reason == "unknown"


def test_a_success_that_is_not_json_is_unavailable_not_a_crash(fake_google: FakeGoogle) -> None:
    fake_google.fail_next(status=200, body=b"not json at all")

    with pytest.raises(google.GoogleUnavailable):
        google.refresh_access_token(settings(), "r-1")


# ---- the rules every call follows --------------------------------------------------------------


def test_every_call_is_https_with_a_short_timeout(fake_google: FakeGoogle) -> None:
    fake_google.grant_code("code-1")
    fake_google.refresh_tokens.add("r-1")

    google.exchange_code(settings(), "code-1")
    google.refresh_access_token(settings(), "r-1")
    google.revoke(settings(), "r-1")

    assert len(fake_google.calls) == 3
    for call in fake_google.calls:
        assert call.url.startswith("https://")
        assert 0 < call.timeout <= 15  # never wait for ever (operations.md)


def test_errors_never_carry_a_token_or_a_secret(fake_google: FakeGoogle) -> None:
    fake_google.fail_next(status=400, body=b'{"error": "invalid_grant", "refresh_token": "LEAK"}')
    fake_google.fail_next(status=503, body=b"echo r-secret-token and test-client-secret-value")

    with pytest.raises(google.GoogleRefused) as refused:
        google.refresh_access_token(settings(), "r-secret-token")
    with pytest.raises(google.GoogleUnavailable) as unavailable:
        google.refresh_access_token(settings(), "r-secret-token")

    for error in (refused.value, unavailable.value):
        text = f"{error} {error!r}"
        for secret in ("r-secret-token", GOOGLE_CLIENT_SECRET, "LEAK"):
            assert secret not in text
