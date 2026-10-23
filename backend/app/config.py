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
