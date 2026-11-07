from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


# A template returns None when there is nothing to send any more (for example the invitation was
# revoked after the email was queued): the job then finishes without sending anything.
Template = Callable[[Session, dict[str, Any]], Email | None]
