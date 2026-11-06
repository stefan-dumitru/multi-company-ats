"""The emails the app sends: a template turns a job's ids into the words of one email.

A template is a function `(db, payload) -> Email`. The payload (from the queued job) holds ids
only; the template loads the recipient and any names itself, and builds links from
`get_app_base_url()`. Templates are added with the feature that sends them (invitations,
verification, password reset), by registering them in TEMPLATES.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


Template = Callable[[Session, dict[str, Any]], Email]

TEMPLATES: dict[str, Template] = {}
