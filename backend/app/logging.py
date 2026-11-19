"""JSON log lines: one object per line, so Railway's log search can filter on fields.

Callers add fields with `extra={...}`. By convention those are ids, counts and outcomes only: never
payloads, addresses or secrets (security.md > Logging).
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# Everything a LogRecord has by itself; anything else on a record came from `extra`.
_STANDARD_FIELDS = set(logging.LogRecord("", logging.INFO, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name, value in record.__dict__.items():
            if name not in _STANDARD_FIELDS:
                entry[name] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        # default=str: a value JSON cannot encode is written as text; logging must never raise.
        return json.dumps(entry, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


# Query parameters that carry a secret: Google's one-time code and our signed state (the OAuth
# way back), and the token in the links we email (verify email, reset password). A parameter is
# matched by its whole name, so "postcode" is not mistaken for "code".
_SECRET_QUERY = re.compile(r"(?P<before>[?&](?:code|state|token)=)[^&\s\"']*")


def _hide(value: object) -> object:
    return _SECRET_QUERY.sub(r"\g<before>[hidden]", value) if isinstance(value, str) else value


class RedactSensitiveQuery(logging.Filter):
    """Blanks secret query values in a log line before it is written. Never drops a line.

    uvicorn's access log prints every request's address, query string included, and the way
    back from Google has the one-time code in it. The code cannot be used without our client
    secret and works once, but a secret has no business in a log (security.md > Logging).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _hide(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_hide(argument) for argument in record.args)
        return True


def redact_access_log() -> None:
    """Install the filter on uvicorn's access log. Safe to call more than once."""
    access_log = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactSensitiveQuery) for item in access_log.filters):
        access_log.addFilter(RedactSensitiveQuery())
