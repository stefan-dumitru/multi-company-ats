"""The JSON log format (operations.md > Observability): one parseable object per line."""

import json
import logging
import sys

from app.logging import JsonFormatter


def make_record(message: str = "job finished", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("ats.worker", logging.INFO, __file__, 1, message, (), None)
    for name, value in extra.items():
        setattr(record, name, value)
    return record


def test_a_log_line_is_one_json_object_with_time_level_and_message() -> None:
    line = JsonFormatter().format(make_record("job finished"))

    entry = json.loads(line)

    assert "\n" not in line
    assert entry["message"] == "job finished"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "ats.worker"
    assert entry["time"].endswith("+00:00")  # UTC, like every timestamp in the project


def test_extra_fields_become_keys() -> None:
    entry = json.loads(JsonFormatter().format(make_record(job_id="abc", attempt=2)))

    assert entry["job_id"] == "abc"
    assert entry["attempt"] == 2


def test_an_exception_is_included_without_breaking_the_single_line() -> None:
    record = make_record("it failed")
    try:
        raise ValueError("boom")
    except ValueError:
        record.exc_info = sys.exc_info()

    line = JsonFormatter().format(record)

    assert "\n" not in line
    assert "ValueError: boom" in json.loads(line)["exception"]


def test_a_value_json_cannot_encode_is_written_as_text_instead_of_crashing() -> None:
    entry = json.loads(JsonFormatter().format(make_record(thing=object())))

    assert isinstance(entry["thing"], str)
