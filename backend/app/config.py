"""All runtime configuration is read from environment variables, in this one module."""

import os
from pathlib import Path


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
