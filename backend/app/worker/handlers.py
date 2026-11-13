"""Which function handles which job type."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_smtp_settings
from app.emails import TEMPLATES
from app.integrations.smtp import send_email
from app.models import BackgroundJob
from app.services import resumes as resumes_service
from app.worker.maintenance import maintenance_job
from app.worker.runner import Handler

logger = logging.getLogger("ats.worker")


def send_email_job(db: Session, job: BackgroundJob) -> None:
    """Render the named template from the job's ids and send it.

    At-least-once: if the email goes out but recording the success fails, the retry sends it again.
    That is the usual trade for email; the idempotency key stops the *queueing* side duplicating.
    """
    template_name = job.payload["template"]
    template = TEMPLATES.get(template_name)
    if template is None:
        raise LookupError(f"No email template named {template_name!r}")
    email = template(db, job.payload)
    if email is None:
        logger.info("nothing to send", extra={"job_id": str(job.id), "template": template_name})
        return
    send_email(get_smtp_settings(), email.to, email.subject, email.body)


def delete_file_job(db: Session, job: BackgroundJob) -> None:
    """Remove a replaced file from storage, unless something still needs it.

    The decision is made now, not when the job was queued. If storage is down this raises, and the
    worker retries with backoff.
    """
    file_id = uuid.UUID(job.payload["file_id"])
    resumes_service.delete_file_if_unused(db, file_id, datetime.now(UTC))


HANDLERS: dict[str, Handler] = {
    "send_email": send_email_job,
    "delete_file": delete_file_job,
    "maintenance": maintenance_job,
}
