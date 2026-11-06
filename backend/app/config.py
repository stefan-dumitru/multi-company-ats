"""All runtime configuration is read from environment variables, in this one module."""

import os
import re
from dataclasses import dataclass, field
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlsplit


def get_static_dir() -> Path | None:
    """Folder holding the built React app. Unset in local development, where Vite serves the UI."""
    value = os.environ.get("STATIC_DIR", "").strip()
    return Path(value) if value else None


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        # Fail loudly and early: a missing setting should stop startup, not surface as a 500 later.
        raise RuntimeError("DATABASE_URL is not set. See .env.example.")
    return url


def get_cookie_secure() -> bool:
    """Whether the session cookie is HTTPS-only. On by default; switch off only for local http."""
    return os.environ.get("COOKIE_SECURE", "true").strip().lower() not in ("false", "0", "no")


DEFAULT_JOB_BACKOFF_SECONDS = (60, 300, 1800, 7200)


def get_job_backoff_seconds() -> tuple[int, ...]:
    """Seconds to wait before retry 1, 2, 3... of a failed job (1 min, 5 min, 30 min, 2 h).

    Only a local demo needs to change this (JOB_BACKOFF_SECONDS="1,1,1,1" to watch retries in
    seconds). A nonsense value stops the program rather than being guessed at.
    """
    raw = os.environ.get("JOB_BACKOFF_SECONDS")
    if raw is None:
        return DEFAULT_JOB_BACKOFF_SECONDS
    try:
        values = tuple(int(part) for part in raw.split(","))
    except ValueError:
        values = ()
    if not values or any(value <= 0 for value in values):
        raise RuntimeError(
            'JOB_BACKOFF_SECONDS must be positive whole numbers separated by commas, e.g. "60,300".'
        )
    return values


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str | None
    password: str | None = field(repr=False)  # repr=False: never printed by accident
    starttls: bool
    sender: str


# Anything that could turn one address into a name, a list, a comment or a second header.
_UNSAFE = r"\s@<>,;:\"()\[\]\\"
_PLAIN_ADDRESS = rf"[^{_UNSAFE}]+@[^{_UNSAFE}]+"


def is_plain_address(value: str) -> bool:
    """One bare address like `sam@example.com`: no name part, no list, no line breaks."""
    return re.fullmatch(_PLAIN_ADDRESS, value) is not None


def get_smtp_settings() -> SmtpSettings:
    """Where and how to send email. Locally this is Mailpit; in production a real provider."""
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("SMTP_HOST is not set. See .env.example.")

    raw_port = os.environ.get("SMTP_PORT", "587").strip()
    if not raw_port.isdecimal() or not 1 <= int(raw_port) <= 65535:
        raise RuntimeError("SMTP_PORT must be a port number between 1 and 65535.")

    # Encrypted by default. Only the private-network Mailpit (no credentials) turns this off.
    starttls = os.environ.get("SMTP_STARTTLS", "true").strip().lower() not in ("false", "0", "no")

    username = os.environ.get("SMTP_USERNAME", "").strip() or None
    password = os.environ.get("SMTP_PASSWORD", "") or None
    if username is not None and password is None:
        raise RuntimeError("SMTP_PASSWORD is not set, but SMTP_USERNAME is.")
    if username is not None and not starttls:
        raise RuntimeError(
            "SMTP_STARTTLS must be on when SMTP_USERNAME is set: no passwords in clear."
        )

    sender = os.environ.get("EMAIL_FROM", "").strip()
    if not sender:
        raise RuntimeError("EMAIL_FROM is not set. See .env.example.")
    if not is_plain_address(parseaddr(sender)[1]) or "\n" in sender or "\r" in sender:
        raise RuntimeError('EMAIL_FROM must be an address, like "ATS <no-reply@example.com>".')

    return SmtpSettings(
        host=host,
        port=int(raw_port),
        username=username,
        password=password,
        starttls=starttls,
        sender=sender,
    )


def get_app_base_url() -> str:
    """The public address of the site, used to build links in emails (no trailing slash)."""
    value = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if not value:
        raise RuntimeError("APP_BASE_URL is not set. See .env.example.")
    parts = urlsplit(value)
    looks_valid = (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and not re.search(r"\s", value)
        and not parts.query
        and not parts.fragment
    )
    if not looks_valid:
        raise RuntimeError("APP_BASE_URL must be a web address like https://ats.example.com.")
    # A link in an email is a credential on its way; over plain http anyone on the path can read it.
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError("APP_BASE_URL must use https (http is allowed only for localhost).")
    return value
