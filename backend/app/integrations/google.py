"""Google: the one module that talks to it (like `storage.py` does for the bucket).

The OAuth side (the address of Google's consent window, exchanging the code that comes back,
refreshing an access token, revoking) and the calendar side (create, change and delete one event).
Rules that matter, kept in one place:

* One outgoing call, `transport`, with an explicit timeout. Tests replace it with a fake Google, so
  nothing in the test suite ever reaches the real one.
* No inline retries: retrying belongs to the background worker (operations.md).
* Two kinds of failure, because callers treat them differently: `GoogleUnavailable` (could not be
  reached, or answered 5xx: try again later) and `GoogleRefused` (Google said no, for example the
  person revoked access: do not keep trying the same thing).
* No error ever carries a token, a code or a secret. They hold a fixed sentence and, for a refusal,
  Google's short error name (checked to be plain letters), nothing else.
"""

import base64
import json
import re
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

from app.config import GoogleSettings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# Events always go on the person's own primary calendar.
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
# The narrowest permission that lets us create, change and delete events (and nothing else).
SCOPE = "https://www.googleapis.com/auth/calendar.events"

# Signing in asks only who the person is: no calendar, and nothing we keep from Google afterwards.
LOGIN_SCOPE = "openid email profile"
# Google puts one of these in the ID token's issuer claim.
LOGIN_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

# Never wait for ever (operations.md > External Services).
TIMEOUT_SECONDS = 10

# What `transport` is: method, url, headers, body, timeout -> status, body.
Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


class GoogleError(Exception):
    """Base for everything this module raises."""


class GoogleUnavailable(GoogleError):
    """Google could not be reached, or had an error of its own. Trying again later may work."""


class GoogleRefused(GoogleError):
    """Google answered no. `reason` is its short error name ("invalid_grant" means the person
    revoked our access), or one of ours ("no_refresh_token", "missing_scope")."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Google refused the request ({reason}).")
        self.reason = reason


@dataclass(frozen=True)
class TokenGrant:
    refresh_token: str = ""
    access_token: str = ""
    scope: str = ""

    def __repr__(self) -> str:  # never print tokens by accident
        return "TokenGrant(...)"


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> tuple[int, bytes]:
    if not url.startswith("https://"):
        raise GoogleUnavailable("Only https addresses are used.")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


# The one place a request leaves the app. Replaced by a fake in tests.
transport: Transport = _urllib_transport

_SAFE_REASON = re.compile(r"[a-z_]{1,40}")


def _send(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes]:
    """The one outgoing call, with the failures every caller treats the same way."""
    try:
        status, payload = transport(method, url, headers, body, TIMEOUT_SECONDS)
    except OSError, TimeoutError:
        # `from None`: the original error's text could echo the request, so it is not kept.
        raise GoogleUnavailable("Google could not be reached.") from None
    if status >= 500:
        raise GoogleUnavailable(f"Google answered {status}.")
    return status, payload


def _refusal(payload: bytes) -> GoogleRefused:
    """Google said no (4xx). Only a short plain-letters error name is kept, never its text."""
    reason = "unknown"
    try:
        error = json.loads(payload).get("error")
        if isinstance(error, str) and _SAFE_REASON.fullmatch(error):
            reason = error
    except ValueError, AttributeError:
        pass
    return GoogleRefused(reason)


def _post(url: str, form: dict[str, str], *, read_answer: bool = True) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "ats",
    }
    status, payload = _send("POST", url, headers, urlencode(form).encode())
    if status >= 400:
        raise _refusal(payload)
    if not read_answer:
        return {}
    try:
        answer = json.loads(payload)
    except ValueError:
        raise GoogleUnavailable("Google sent an answer that could not be read.") from None
    if not isinstance(answer, dict):
        raise GoogleUnavailable("Google sent an answer that could not be read.")
    return answer


def authorization_url(settings: GoogleSettings, state: str) -> str:
    """Where to send the browser so the person can agree to let us use their calendar."""
    query = urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            # We create events while the person is away, so we need to be able to renew access...
            "access_type": "offline",
            # ...and `consent` makes Google hand over a refresh token every time, not just once.
            "prompt": "consent",
            "include_granted_scopes": "false",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def exchange_code(settings: GoogleSettings, code: str) -> TokenGrant:
    """Trade the one-time code Google sent back for a refresh token."""
    answer = _post(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "redirect_uri": settings.redirect_uri,
        },
    )
    refresh_token = answer.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise GoogleRefused("no_refresh_token")
    scope = answer.get("scope")
    # The person may have unticked what we asked for in Google's window.
    if not isinstance(scope, str) or SCOPE not in scope.split():
        raise GoogleRefused("missing_scope")
    access_token = answer.get("access_token")
    return TokenGrant(
        refresh_token=refresh_token,
        access_token=access_token if isinstance(access_token, str) else "",
        scope=scope,
    )


@dataclass(frozen=True)
class GoogleIdentity:
    """Who Google says the person is. `subject` is Google's own id for them: it never changes."""

    subject: str
    email: str
    email_verified: bool
    full_name: str


def login_authorization_url(settings: GoogleSettings, state: str) -> str:
    """Where to send the browser so the person can say who they are (and nothing more)."""
    query = urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.login_redirect_uri,
            "response_type": "code",
            "scope": LOGIN_SCOPE,
            # Always show the account chooser: a shared computer must not sign in as whoever was
            # last signed in to Google.
            "prompt": "select_account",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def exchange_login_code(settings: GoogleSettings, code: str, now: datetime) -> GoogleIdentity:
    """Trade the one-time code for who the person is.

    The ID token comes straight from Google's token endpoint over TLS, so its signature is not
    checked (OpenID Connect Core 3.1.3.7 allows that); what it says is still checked: that it is
    from Google, for this app, and not expired.
    """
    answer = _post(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "redirect_uri": settings.login_redirect_uri,
        },
    )
    id_token = answer.get("id_token")
    if not isinstance(id_token, str):
        raise GoogleRefused("no_id_token")
    return _read_id_token(settings, id_token, now)


def _read_id_token(settings: GoogleSettings, id_token: str, now: datetime) -> GoogleIdentity:
    claims = _claims_of(id_token)
    audience = claims.get("aud")
    audience_ok = audience == settings.client_id or (
        isinstance(audience, list) and settings.client_id in audience
    )
    expires = claims.get("exp")
    subject = claims.get("sub")
    email = claims.get("email")
    name = claims.get("name")
    # `bool` is a kind of int in Python, so it is ruled out for the expiry explicitly.
    not_expired = (
        isinstance(expires, int)
        and not isinstance(expires, bool)
        and expires > int(now.timestamp())
    )
    if (
        claims.get("iss") not in LOGIN_ISSUERS
        or not audience_ok
        or not not_expired
        or not isinstance(subject, str)
        or not 0 < len(subject) <= 255
        or not isinstance(email, str)
        or not 0 < len(email) <= 320
    ):
        raise GoogleRefused("bad_id_token")
    return GoogleIdentity(
        subject=subject,
        email=email,
        # Seen as a real boolean and, at times, as the word "true".
        email_verified=claims.get("email_verified") in (True, "true"),
        full_name=name.strip() if isinstance(name, str) else "",
    )


def _claims_of(id_token: str) -> dict[str, Any]:
    """The middle part of a JWT: base64url-encoded JSON. Anything else is "not a valid token"."""
    parts = id_token.split(".")
    if len(parts) != 3:
        raise GoogleRefused("bad_id_token")
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except ValueError:
        raise GoogleRefused("bad_id_token") from None
    if not isinstance(claims, dict):
        raise GoogleRefused("bad_id_token")
    return claims


def refresh_access_token(settings: GoogleSettings, refresh_token: str) -> str:
    """A short-lived access token, from the stored refresh token. Raises GoogleRefused with reason
    "invalid_grant" if the person has since taken our access away."""
    answer = _post(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
        },
    )
    access_token = answer.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise GoogleUnavailable("Google sent an answer that could not be read.")
    return access_token


def revoke(settings: GoogleSettings, refresh_token: str) -> None:
    """Ask Google to forget this token. Callers treat a failure as non-fatal."""
    _post(REVOKE_URL, {"token": refresh_token}, read_answer=False)


# ---- events ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EventDetails:
    """What goes on the calendar. Times go out in UTC; Google shows them in the owner's zone."""

    title: str
    description: str
    location: str
    starts_at: datetime
    ends_at: datetime
    attendee_emails: tuple[str, ...]


def event_id_for(interview_id: uuid.UUID) -> str:
    """The same interview always gets the same event id (Google allows lowercase letters a-v and
    digits, 5 to 1024 long). That is what makes a retry safe: creating it twice is refused, and we
    then change the one that exists instead of leaving two."""
    return interview_id.hex


def _utc(moment: datetime) -> dict[str, str]:
    return {"dateTime": moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "timeZone": "UTC"}


def _event_body(details: EventDetails) -> dict[str, Any]:
    return {
        "summary": details.title,
        "description": details.description,
        "location": details.location,
        "start": _utc(details.starts_at),
        "end": _utc(details.ends_at),
        "attendees": [{"email": email} for email in details.attendee_emails],
        # Patching an event that was deleted in Google brings it back.
        "status": "confirmed",
    }


def _call_events(
    access_token: str, method: str, event_id: str | None, body: dict[str, Any] | None
) -> tuple[int, bytes]:
    url = EVENTS_URL if event_id is None else f"{EVENTS_URL}/{quote(event_id, safe='')}"
    # Google's own invitation emails are off: ours already go out, and two would confuse people.
    url += "?sendUpdates=none"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ats",
    }
    data = json.dumps(body).encode() if body is not None else None
    return _send(method, url, headers, data)


def upsert_event(access_token: str, event_id: str, details: EventDetails) -> None:
    """Create the event, or change it if it is already there."""
    body = _event_body(details)
    status, payload = _call_events(access_token, "POST", None, {"id": event_id, **body})
    if status == 409:  # already created (an earlier attempt got that far)
        status, payload = _call_events(access_token, "PATCH", event_id, body)
    if status >= 400:
        raise _refusal(payload)


def delete_event(access_token: str, event_id: str) -> None:
    """Remove the event. One that is already gone counts as removed."""
    status, payload = _call_events(access_token, "DELETE", event_id, None)
    if status in (404, 410):
        return
    if status >= 400:
        raise _refusal(payload)
