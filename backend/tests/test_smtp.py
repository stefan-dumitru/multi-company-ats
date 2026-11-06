"""The SMTP sender (operations.md > External Integrations).

Rules under test: what we send is plain text and well formed; nothing a user typed can add a
header or a recipient; a dead or silent mail server fails fast instead of hanging the worker; and
a real message really arrives (checked against Mailpit, a real SMTP server).
"""

import socket
import threading
import time
from collections.abc import Iterator

import pytest

from app.config import SmtpSettings
from app.integrations.smtp import build_message, send_email
from tests import mailpit

SETTINGS = mailpit.MAILPIT_SETTINGS


@pytest.fixture
def inbox() -> Iterator[None]:
    mailpit.clear_inbox()
    yield
    mailpit.clear_inbox()


# ---- building the message -----------------------------------------------------------------


def test_the_message_carries_sender_recipient_subject_and_body() -> None:
    message = build_message(SETTINGS.sender, "sam@example.test", "Hello", "Line one\nLine two\n")

    assert message["From"] == "ATS <no-reply@ats.test>"
    assert message["To"] == "sam@example.test"
    assert message["Subject"] == "Hello"
    assert message.get_content_type() == "text/plain"
    assert message.get_content() == "Line one\nLine two\n"


def test_the_message_has_a_date_and_a_unique_id_as_mail_servers_expect() -> None:
    first = build_message(SETTINGS.sender, "sam@example.test", "Hi", "x")
    second = build_message(SETTINGS.sender, "sam@example.test", "Hi", "x")

    assert first["Date"]
    assert first["Message-ID"].endswith("@ats.test>")
    assert first["Message-ID"] != second["Message-ID"]


def test_html_in_user_supplied_text_stays_as_plain_text() -> None:
    # Names and company names are typed by users; the email is never HTML, so this is inert.
    message = build_message(SETTINGS.sender, "sam@example.test", "Hi", "<script>alert(1)</script>")

    assert message.get_content_type() == "text/plain"
    assert message.get_content() == "<script>alert(1)</script>\n"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_a_line_break_in_the_subject_is_refused(newline: str) -> None:
    # "Acme\nBcc: attacker@evil.test" as a company name must not become a header.
    with pytest.raises(ValueError, match="subject"):
        build_message(SETTINGS.sender, "sam@example.test", f"Acme{newline}Bcc: a@evil.test", "x")


@pytest.mark.parametrize(
    "recipient",
    [
        "sam@example.test\nBcc: a@evil.test",
        "sam@example.test, other@example.test",
        "sam@example.test;other@example.test",
        "Sam <sam@example.test>",
        "no-at-sign",
        "two@@example.test",
        "",
    ],
)
def test_only_one_plain_address_is_accepted_as_recipient(recipient: str) -> None:
    with pytest.raises(ValueError, match="recipient"):
        build_message(SETTINGS.sender, recipient, "Hi", "x")


# ---- sending ------------------------------------------------------------------------------


def test_a_message_really_arrives_at_the_mail_server(inbox: None) -> None:
    send_email(SETTINGS, "sam@example.test", "Welcome aboard", "Hello Sam.\n")

    (received,) = mailpit.messages()
    assert received["Subject"] == "Welcome aboard"
    assert received["From"]["Address"] == "no-reply@ats.test"
    assert [to["Address"] for to in received["To"]] == ["sam@example.test"]
    assert received["Text"].strip() == "Hello Sam."
    assert received["HTML"] == ""  # plain text only


def test_a_refused_connection_fails_instead_of_being_ignored() -> None:
    nothing_listens_here = SmtpSettings(**{**SETTINGS.__dict__, "port": 1})

    with pytest.raises(OSError):
        send_email(nothing_listens_here, "sam@example.test", "Hi", "x", timeout=2)


def test_a_server_that_never_answers_is_given_up_on_after_the_timeout() -> None:
    # Accepts the connection, then says nothing: without a timeout the worker would hang forever.
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()
    port = silent.getsockname()[1]
    accepted: list[socket.socket] = []
    threading.Thread(target=lambda: accepted.append(silent.accept()[0]), daemon=True).start()
    settings = SmtpSettings(**{**SETTINGS.__dict__, "port": port})

    started = time.monotonic()
    try:
        with pytest.raises(OSError):  # TimeoutError is an OSError
            send_email(settings, "sam@example.test", "Hi", "x", timeout=0.5)
    finally:
        silent.close()
        for connection in accepted:
            connection.close()

    assert time.monotonic() - started < 5


def test_the_default_timeout_is_ten_seconds() -> None:
    from app.integrations import smtp

    assert smtp.TIMEOUT_SECONDS == 10
