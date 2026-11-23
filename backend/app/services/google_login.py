"""Signing in with Google (functional.md > Sign in with Google and link accounts).

Who ends up signed in, in this order:

1. A person whose Google id we already know: that same person, even if their email changed.
2. Otherwise, an account with the same email: linked only if Google says the email is verified AND
   the account's email is verified too (so nobody can claim an account by registering its address
   without owning the inbox). Anything else is refused and nothing is linked.
3. Otherwise a new candidate, already verified, with no password.

Google never grants a role: a person keeps the role they have, and a new account is always a
candidate. A deactivated or anonymized account is refused whichever way it is found.
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import tokens
from app.config import get_google_settings
from app.integrations import google
from app.models import CandidateProfile, ExternalIdentity, Role, User
from app.services.audit import record_audit
from app.services.users import normalize_email

logger = logging.getLogger(__name__)

# How long a person has to finish in Google's window before the way back stops working.
MAX_STATE_AGE = timedelta(minutes=10)
PROVIDER = "google"
MAX_NAME_LENGTH = 200


class GoogleLoginError(Exception):
    """The way back from Google did not end in a sign-in. `reason` is one short code that the login
    page turns into words; Google's own text is never passed on."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def start_login(now: datetime) -> tuple[str, str]:
    """The address of Google's window, and the random value this browser must keep (in a cookie).

    The state in the address is signed and carries that value, so the way back only works for the
    browser that started: otherwise someone could start a sign-in, send the way-back address to a
    victim, and sign the victim in as themselves ("login CSRF").
    """
    settings = get_google_settings()
    if settings is None:
        raise GoogleLoginError("not_configured")
    nonce = uuid.uuid4()
    # The state signer takes a person's id; here nobody is signed in yet, so it signs the nonce.
    state = tokens.make_state(tokens.GOOGLE_LOGIN, nonce, now)
    return google.login_authorization_url(settings, state), str(nonce)


def finish_login(
    db: Session,
    now: datetime,
    *,
    code: str | None,
    state: str | None,
    error: str | None,
    nonce: str | None,
) -> User:
    """Who Google says is at the keyboard, as one of our users. The caller commits (or rolls back).

    Raises `GoogleLoginError` unless somebody may be signed in."""
    settings = get_google_settings()
    if settings is None:
        raise GoogleLoginError("not_configured")
    if error is not None:
        # They said no, or Google had a problem. Never repeat Google's words back.
        raise GoogleLoginError("access_denied" if error == "access_denied" else "google_error")
    if not _state_is_ours(state, nonce, now):
        raise GoogleLoginError("bad_state")
    if not code:
        raise GoogleLoginError("missing_code")

    try:
        identity = google.exchange_login_code(settings, code, now)
    except google.GoogleUnavailable:
        raise GoogleLoginError("google_unavailable") from None
    except google.GoogleRefused:
        raise GoogleLoginError("google_refused") from None

    try:
        return _user_for(db, identity, now)
    except IntegrityError:
        # Two sign-ins for the same person at the same moment: the database let only one through.
        # The other is asked to press the button again, and will then find the first one's work.
        logger.warning("two google sign-ins met at once")
        raise GoogleLoginError("try_again") from None


def _state_is_ours(state: str | None, nonce: str | None, now: datetime) -> bool:
    """The state is genuine and recent, and it was made for the browser holding this cookie."""
    if not state or not nonce:
        return False
    made_for = tokens.read_state(tokens.GOOGLE_LOGIN, state, now, MAX_STATE_AGE)
    try:
        return made_for is not None and made_for == uuid.UUID(nonce)
    except ValueError:
        return False


def _user_for(db: Session, identity: google.GoogleIdentity, now: datetime) -> User:
    known = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == PROVIDER, ExternalIdentity.subject == identity.subject
        )
    )
    if known is not None:
        user = db.get(User, known.user_id)
        if user is None or not _may_sign_in(user):
            raise GoogleLoginError("account_unavailable")
        return user

    # From here on the email is what is being relied on, so Google must vouch for it.
    if not identity.email_verified:
        raise GoogleLoginError("email_not_verified")
    email = normalize_email(identity.email)
    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is None:
        return _create_candidate(db, identity, email, now)
    if not _may_sign_in(existing):
        raise GoogleLoginError("account_unavailable")
    if existing.email_verified_at is None:
        # Whoever registered this address may not own the inbox: they must prove it first.
        raise GoogleLoginError("account_unverified")
    _link(db, existing, identity, now)
    return existing


def _may_sign_in(user: User) -> bool:
    return user.is_active and user.anonymized_at is None


def _link(db: Session, user: User, identity: google.GoogleIdentity, now: datetime) -> None:
    db.add(ExternalIdentity(user_id=user.id, provider=PROVIDER, subject=identity.subject))
    db.flush()
    _audit(db, user, "account.google_linked", now)


def _create_candidate(
    db: Session, identity: google.GoogleIdentity, email: str, now: datetime
) -> User:
    # Google may send no name; the part of the address before the @ is a better start than blank.
    name = identity.full_name or email.split("@")[0]
    candidate = User(
        company_id=None,
        role=Role.CANDIDATE,
        email=email,
        full_name=name[:MAX_NAME_LENGTH],
        password_hash=None,  # Google is how they sign in; "forgot password" can add one later
        email_verified_at=now,  # Google vouched for the address
    )
    db.add(candidate)
    db.flush()
    db.add(CandidateProfile(user_id=candidate.id))
    db.add(ExternalIdentity(user_id=candidate.id, provider=PROVIDER, subject=identity.subject))
    db.flush()
    _audit(db, candidate, "account.google_created", now)
    return candidate


def _audit(db: Session, user: User, action: str, now: datetime) -> None:
    record_audit(
        db,
        actor=user,
        action=action,
        entity_type="user",
        entity_id=user.id,
        old_value=None,
        new_value={"provider": PROVIDER},  # never the Google id or the address
        now=now,
    )
