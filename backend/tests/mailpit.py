"""Test helper: read what the app sent from Mailpit's HTTP API (the fake mail server).

Local: `docker compose up -d --wait`. CI: a Mailpit service container. Same ports both places.
"""

import json
import urllib.request
from typing import Any

from app.config import SmtpSettings

MAILPIT_API = "http://127.0.0.1:8025/api/v1"
MAILPIT_SETTINGS = SmtpSettings(
    host="127.0.0.1",
    port=1025,
    username=None,
    password=None,
    starttls=False,
    sender="ATS <no-reply@ats.test>",
)


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        MAILPIT_API + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        text = response.read().decode()
    # Reading answers are JSON; Mailpit answers a delete with the plain word "ok".
    return json.loads(text) if text.startswith(("{", "[")) else text


def clear_inbox() -> None:
    _call("DELETE", "/messages")


def messages() -> list[dict[str, Any]]:
    """Every message in the inbox, full detail (headers, text), oldest first."""
    summaries = _call("GET", "/messages?limit=200")["messages"]
    return [_call("GET", f"/message/{summary['ID']}") for summary in reversed(summaries)]
