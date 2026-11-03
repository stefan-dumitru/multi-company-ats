"""Login rate limiting, kept in the database so it needs no extra service (security.md)."""

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import LoginAttempt

WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_EMAIL = 5
MAX_FAILURES_PER_IP = 20


def hash_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def record_failure(db: Session, email: str, ip_address: str, now: datetime) -> None:
    db.add(LoginAttempt(email_hash=hash_email(email), ip_address=ip_address, attempted_at=now))


def is_locked_out(db: Session, email: str, ip_address: str, now: datetime) -> bool:
    since = now - WINDOW
    email_failures = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.email_hash == hash_email(email), LoginAttempt.attempted_at > since)
    )
    ip_failures = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.ip_address == ip_address, LoginAttempt.attempted_at > since)
    )
    return (email_failures or 0) >= MAX_FAILURES_PER_EMAIL or (
        ip_failures or 0
    ) >= MAX_FAILURES_PER_IP


def clear_failures(db: Session, email: str) -> None:
    """After a successful login the earlier typos no longer count against the address."""
    db.execute(delete(LoginAttempt).where(LoginAttempt.email_hash == hash_email(email)))
