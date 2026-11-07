"""The emails the app sends: a template turns a job's ids into the words of one email.

A template is a function `(db, payload) -> Email | None`. The payload (from the queued job) holds
ids only; the template loads the recipient and any names itself, and builds links from
`get_app_base_url()` and the signing key. Templates are registered here, by the name the queueing
code puts in the payload.
"""

from app.emails.base import Email, Template
from app.emails.invitation import render_invitation

TEMPLATES: dict[str, Template] = {"invitation": render_invitation}

__all__ = ["TEMPLATES", "Email", "Template"]
