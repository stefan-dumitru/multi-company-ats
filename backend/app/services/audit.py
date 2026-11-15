"""Append-only audit trail (data-model.md > AuditLog).

The caller commits: the audit row and the change it describes are one transaction, so a change
never exists without its record, and a record never describes a change that did not happen.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit(
    db: Session,
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    old_value: dict[str, Any] | None,
    new_value: dict[str, Any] | None,
    now: datetime,
    company_id: uuid.UUID | None = None,
) -> None:
    # `company_id` is for actors that have none (a candidate): the row is filed under the company
    # the action concerns. Staff actions use the actor's own company.
    # Values hold only what changed (a role, a flag). Never passwords, tokens or personal details.
    db.add(
        AuditLog(
            company_id=company_id if company_id is not None else actor.company_id,
            actor_user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            created_at=now,
        )
    )
