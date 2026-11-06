"""JSON log lines: one object per line, so Railway's log search can filter on fields.

Callers add fields with `extra={...}`. By convention those are ids, counts and outcomes only: never
payloads, addresses or secrets (security.md > Logging).
"""

import json
import logging
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
