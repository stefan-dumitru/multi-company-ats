"""The emails the app sends: a template turns a job's ids into the words of one email.

A template is a function `(db, payload) -> Email | None`. The payload (from the queued job) holds
ids only; the template loads the recipient and any names itself, and builds links from
`get_app_base_url()` and the signing key. Templates are registered here, by the name the queueing
code puts in the payload.
"""

from app.emails.base import Email, Template
from app.emails.invitation import render_invitation
from app.emails.password_changed import render_password_changed
from app.emails.reset_password import render_reset_password
from app.emails.verify_email import render_verify_email

TEMPLATES: dict[str, Template] = {
    "invitation": render_invitation,
    "verify_email": render_verify_email,
    "reset_password": render_reset_password,
    "password_changed": render_password_changed,
}

__all__ = ["TEMPLATES", "Email", "Template"]
