"""Google: the one module that talks to it (like `storage.py` does for the bucket).

Only the OAuth side lives here for now: the address of Google's consent window, exchanging the code
that comes back, refreshing an access token, and revoking. Rules that matter, kept in one place:

* One outgoing call, `transport`, with an explicit timeout. Tests replace it with a fake Google, so
  nothing in the test suite ever reaches the real one.
* No inline retries: retrying belongs to the background worker (operations.md).
* Two kinds of failure, because callers treat them differently: `GoogleUnavailable` (could not be
  reached, or answered 5xx: try again later) and `GoogleRefused` (Google said no, for example the
  person revoked access: do not keep trying the same thing).
* No error ever carries a token, a code or a secret. They hold a fixed sentence and, for a refusal,
  Google's short error name (checked to be plain letters), nothing else.
"""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from app.config import GoogleSettings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# The narrowest permission that lets us create, change and delete events (and nothing else).
SCOPE = "https://www.googleapis.com/auth/calendar.events"

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


def _post(url: str, form: dict[str, str], *, read_answer: bool = True) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": "ats",
    }
    try:
        status, payload = transport("POST", url, headers, urlencode(form).encode(), TIMEOUT_SECONDS)
    except OSError, TimeoutError:
        # `from None`: the original error's text could echo the request, so it is not kept.
        raise GoogleUnavailable("Google could not be reached.") from None

    if status >= 500:
        raise GoogleUnavailable(f"Google answered {status}.")
    if status >= 400:
        reason = "unknown"
        try:
            error = json.loads(payload).get("error")
            if isinstance(error, str) and _SAFE_REASON.fullmatch(error):
                reason = error
        except ValueError, AttributeError:
            pass
        raise GoogleRefused(reason)
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
