"""Signed links for emails: invitation, email verification, password reset.

A link is `<row id>.<signature>`. The signature is an HMAC-SHA256, keyed with SECRET_KEY, over the
purpose and the row id. Why signed instead of random-and-stored:

* An email has to contain the real link, but the job queue must hold no secrets. With a signed
  link the queue holds only the row id, and the worker rebuilds the same link when it sends.
* Nothing secret is stored in the database either; a database leak yields no usable links.

The purpose is part of what is signed, so a link made for one thing (a password reset) cannot be
used for another (an invitation). Rotating SECRET_KEY invalidates every outstanding link: that is
the emergency switch, and it is documented in security.md.

A valid signature only proves *we* issued the link for that row. Whether the row may still be used
(not expired, not already used, not revoked) is checked by the caller against the database.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

from app.config import get_secret_key

INVITATION = "invitation"
EMAIL_VERIFICATION = "email_verification"
PASSWORD_RESET = "password_reset"
GOOGLE_CALENDAR = "google_calendar"

# A real link is 36 + 1 + 64 characters; anything much longer is not worth looking at.
MAX_TOKEN_LENGTH = 200


def _sign(purpose: str, row_id: uuid.UUID) -> str:
    message = f"{purpose}:{row_id}".encode()
    return hmac.new(get_secret_key().encode(), message, hashlib.sha256).hexdigest()


def make_token(purpose: str, row_id: uuid.UUID) -> str:
    return f"{row_id}.{_sign(purpose, row_id)}"


def read_token(purpose: str, token: str) -> uuid.UUID | None:
    """The row id the link was issued for, or None for anything that is not a genuine link.

    Never raises on bad input: a garbled link is an ordinary "no", not an error.
    """
    if len(token) > MAX_TOKEN_LENGTH:
        return None
    id_part, separator, signature = token.partition(".")
    if not separator:
        return None
    try:
        row_id = uuid.UUID(id_part)
    except ValueError:
        return None
    expected = _sign(purpose, row_id)
    # Constant-time comparison, so response timing reveals nothing about how much matched.
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        return None
    return row_id


# A little slack for two clocks that disagree by a moment.
_CLOCK_SKEW = timedelta(seconds=60)


def _sign_state(purpose: str, user_id: uuid.UUID, issued_at: int) -> str:
    message = f"{purpose}:{user_id}:{issued_at}".encode()
    return hmac.new(get_secret_key().encode(), message, hashlib.sha256).hexdigest()


def make_state(purpose: str, user_id: uuid.UUID, now: datetime) -> str:
    """A short-lived, signed note "this person started this", for a round trip through another
    site (Google's consent window). Unlike a link it names a person and a moment, and it is only
    good for a little while: `read_state` checks both."""
    issued_at = int(now.timestamp())
    return f"{user_id}.{issued_at}.{_sign_state(purpose, user_id, issued_at)}"


def read_state(purpose: str, state: str, now: datetime, max_age: timedelta) -> uuid.UUID | None:
    """The person the state was made for, or None for anything that is not genuine and recent.

    Never raises on bad input: a garbled or stale state is an ordinary "no".
    """
    if len(state) > MAX_TOKEN_LENGTH:
        return None
    parts = state.split(".")
    if len(parts) != 3:
        return None
    try:
        user_id = uuid.UUID(parts[0])
        issued_at = int(parts[1])
        issued = datetime.fromtimestamp(issued_at, UTC)
    except ValueError, OverflowError, OSError:
        return None
    expected = _sign_state(purpose, user_id, issued_at)
    if not hmac.compare_digest(expected.encode(), parts[2].encode()):
        return None
    if issued > now + _CLOCK_SKEW or now - issued > max_age:
        return None
    return user_id
