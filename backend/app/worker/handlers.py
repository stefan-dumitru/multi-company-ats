"""Which function handles which job type."""

from sqlalchemy.orm import Session

from app.config import get_smtp_settings
from app.emails import TEMPLATES
from app.integrations.smtp import send_email
from app.models import BackgroundJob
from app.worker.runner import Handler


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
    send_email(get_smtp_settings(), email.to, email.subject, email.body)


HANDLERS: dict[str, Handler] = {"send_email": send_email_job}
