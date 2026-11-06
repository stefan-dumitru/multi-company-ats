"""Sending email over SMTP (operations.md > External Integrations).

Plain text only, on purpose: names and company names are typed by users, and plain text cannot
carry a script or markup. Everything that goes into a header is checked for line breaks, because a
line break is how a typed value would add a header (a hidden Bcc) to the message.
"""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from app.config import SmtpSettings, is_plain_address

# Every network step gets this long. Without it a mail server that stops answering would freeze the
# worker (and the job's attempt would never be recorded).
TIMEOUT_SECONDS = 10


def build_message(sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    if not is_plain_address(recipient):
        raise ValueError("The recipient must be one plain email address.")
    sender_address = parseaddr(sender)[1]
    if not is_plain_address(sender_address) or "\n" in sender or "\r" in sender:
        raise ValueError("The sender is not a valid address.")
    if "\n" in subject or "\r" in subject:
        raise ValueError("The subject must not contain line breaks.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender_address.rsplit("@", 1)[1])
    message.set_content(body)  # text/plain
    return message


def send_email(
    settings: SmtpSettings,
    recipient: str,
    subject: str,
    body: str,
    timeout: float = TIMEOUT_SECONDS,
) -> None:
    """Send one email. Raises on any failure (the worker records it and retries later)."""
    message = build_message(settings.sender, recipient, subject, body)
    with smtplib.SMTP(settings.host, settings.port, timeout=timeout) as connection:
        if settings.starttls:
            connection.starttls(context=ssl.create_default_context())
        if settings.username is not None and settings.password is not None:
            connection.login(settings.username, settings.password)
        connection.send_message(message)
