"""The JSON log format (operations.md > Observability): one parseable object per line."""

import json
import logging
import sys

from app.logging import JsonFormatter, RedactSensitiveQuery


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


# ---- secrets in web addresses -------------------------------------------------------------
# uvicorn writes a line like `GET /path?query HTTP/1.1` for every request. Google's one-time code,
# the signed state and the links in emails carry secrets in that query, so those values are blanked.


def access_record(path: str) -> logging.LogRecord:
    """A record shaped like uvicorn's access log line."""
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", path, "1.1", 303), None,
    )  # fmt: skip


def logged(path: str) -> str:
    record = access_record(path)
    assert RedactSensitiveQuery().filter(record) is True  # never drops a line, only blanks values
    return record.getMessage()


def test_googles_code_and_our_state_never_reach_the_access_log() -> None:
    line = logged("/api/calendar/callback?code=4/0AbCd-secret&state=abc.123.sig")

    assert "4/0AbCd-secret" not in line and "abc.123.sig" not in line
    assert "/api/calendar/callback?code=[hidden]&state=[hidden]" in line


def test_the_token_in_an_emailed_link_is_hidden_too() -> None:
    for path in ("/verify-email?token=ID.SIGNATURE", "/reset-password?token=ID.SIGNATURE"):
        assert "ID.SIGNATURE" not in logged(path)


def test_other_parameters_and_ordinary_paths_are_left_alone() -> None:
    assert "page=2&page_size=20" in logged("/api/jobs?page=2&page_size=20")
    assert "q=python&location=oslo" in logged("/api/public/jobs?q=python&location=oslo")
    assert "/health" in logged("/health")


def test_a_secret_among_other_parameters_is_still_found() -> None:
    line = logged("/x?a=1&code=SECRET&b=2")

    assert "SECRET" not in line and "a=1" in line and "b=2" in line


def test_a_parameter_that_only_ends_in_the_word_is_not_touched() -> None:
    assert "postcode=0150" in logged("/x?postcode=0150")


def test_the_status_and_the_rest_of_the_line_survive() -> None:
    line = logged("/api/calendar/callback?code=SECRET")

    assert line == '127.0.0.1:5000 - "GET /api/calendar/callback?code=[hidden] HTTP/1.1" 303'


def test_a_line_that_is_only_text_is_cleaned_as_well() -> None:
    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "GET /a?code=SECRET failed", (), None
    )

    RedactSensitiveQuery().filter(record)

    assert "SECRET" not in record.getMessage()


def test_the_web_app_installs_the_filter_on_uvicorns_access_log() -> None:
    import app.main  # noqa: F401 - importing the app is what installs it

    filters = logging.getLogger("uvicorn.access").filters
    assert any(isinstance(item, RedactSensitiveQuery) for item in filters)
