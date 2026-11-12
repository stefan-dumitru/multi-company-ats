"""The storage wrapper (integrations/storage.py), against a real S3-compatible server.

The server is the one from docker compose locally and the one the pull request pipeline starts.
Each test gets a fresh, empty bucket, so tests cannot affect each other.
"""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from botocore.exceptions import ConnectionError as BotoConnectionError

from app.config import StorageSettings
from app.integrations import storage
from app.integrations.storage import (
    ObjectNotFound,
    StorageNotConfigured,
    StorageUnavailable,
    delete_object,
    open_object,
    put_object,
)

S3_NAMES = [
    "S3_ENDPOINT_URL",
    "S3_BUCKET",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_REGION",
    "S3_ADDRESSING_STYLE",
]


def read_all(key: str) -> bytes:
    return b"".join(open_object(key).chunks)


# ---- the real round trip -----------------------------------------------------------------


def test_a_stored_object_comes_back_unchanged(storage_bucket: str) -> None:
    put_object("resumes/one", b"hello resume", "application/pdf")

    stored = open_object("resumes/one")

    assert b"".join(stored.chunks) == b"hello resume"
    assert stored.size == len(b"hello resume")
    assert stored.content_type == "application/pdf"


def test_binary_data_survives(storage_bucket: str) -> None:
    data = bytes(range(256)) * 100

    put_object("resumes/binary", data, "application/octet-stream")

    assert read_all("resumes/binary") == data


def test_a_large_object_arrives_in_several_pieces(storage_bucket: str) -> None:
    data = b"x" * (5 * 1024 * 1024)
    put_object("resumes/big", data, "application/pdf")

    stored = open_object("resumes/big")
    pieces = list(stored.chunks)

    assert len(pieces) > 1  # streamed, not one 5 MB blob
    assert b"".join(pieces) == data
    assert stored.size == len(data)


def test_storing_under_the_same_key_replaces_the_object(storage_bucket: str) -> None:
    put_object("resumes/same", b"first", "application/pdf")
    put_object("resumes/same", b"second", "application/pdf")

    assert read_all("resumes/same") == b"second"


def test_an_empty_object_is_allowed_by_the_storage_layer(storage_bucket: str) -> None:
    # What counts as a valid resume is decided by the upload rules, not here.
    put_object("resumes/empty", b"", "application/pdf")

    assert read_all("resumes/empty") == b""


def test_a_missing_object_is_reported_as_not_found(storage_bucket: str) -> None:
    with pytest.raises(ObjectNotFound):
        open_object("resumes/does-not-exist")


def test_deleting_removes_the_object(storage_bucket: str) -> None:
    put_object("resumes/gone", b"data", "application/pdf")

    delete_object("resumes/gone")

    with pytest.raises(ObjectNotFound):
        open_object("resumes/gone")


def test_deleting_something_that_is_not_there_is_not_an_error(storage_bucket: str) -> None:
    delete_object("resumes/never-existed")
    delete_object("resumes/never-existed")


# ---- when storage is missing or broken ---------------------------------------------------


def test_without_settings_every_call_says_storage_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in S3_NAMES:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(StorageNotConfigured):
        put_object("k", b"x", "application/pdf")
    with pytest.raises(StorageNotConfigured):
        open_object("k")
    with pytest.raises(StorageNotConfigured):
        delete_object("k")


def test_half_finished_settings_are_reported_as_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in S3_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("S3_BUCKET", "ats-resumes")

    with pytest.raises(StorageNotConfigured, match="S3_ENDPOINT_URL"):
        open_object("k")


def test_an_unreachable_server_fails_fast_instead_of_hanging(
    storage_bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:1")  # nothing listens there
    started = time.monotonic()

    with pytest.raises(StorageUnavailable):
        put_object("resumes/x", b"data", "application/pdf")

    assert time.monotonic() - started < storage.CONNECT_TIMEOUT_SECONDS + 5


def test_wrong_credentials_are_unavailable_and_the_secret_is_never_in_the_message(
    storage_bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "definitely-the-wrong-secret")

    with pytest.raises(StorageUnavailable) as raised:
        open_object("resumes/x")

    assert "definitely-the-wrong-secret" not in str(raised.value)
    assert "definitely-the-wrong-secret" not in repr(raised.value.__cause__)


def test_a_bucket_that_does_not_exist_is_unavailable_not_not_found(
    storage_bucket: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("S3_BUCKET", "this-bucket-does-not-exist")

    # "No such object" must stay reserved for a missing key: a missing bucket is a setup problem.
    with pytest.raises(StorageUnavailable):
        open_object("resumes/x")


@pytest.mark.parametrize("failure", ["wrong secret", "nobody listening"])
def test_failures_are_logged_without_the_key_or_secrets(
    storage_bucket: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    if failure == "wrong secret":
        monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "definitely-the-wrong-secret")
    else:
        # botocore's own message for this failure contains the whole address, key included.
        monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:1")

    with pytest.raises(StorageUnavailable):
        open_object("resumes/secret-looking-key")

    assert "Storage get failed" in caplog.text
    assert "definitely-the-wrong-secret" not in caplog.text
    assert "secret-looking-key" not in caplog.text


# ---- guard rails on how the client is made -----------------------------------------------


def test_the_client_has_timeouts_and_no_inline_retries(storage_bucket: str) -> None:
    settings, client = storage._settings_and_client()

    config = client.meta.config
    assert config.connect_timeout == storage.CONNECT_TIMEOUT_SECONDS
    assert config.read_timeout == storage.READ_TIMEOUT_SECONDS
    assert config.retries["total_max_attempts"] == 1  # one try, no retries
    assert settings.bucket == storage_bucket


# ---- the stream is always closed ---------------------------------------------------------


class FakeBody:
    def __init__(self, pieces: list[bytes], fail_after: int | None = None) -> None:
        self.pieces = pieces
        self.fail_after = fail_after
        self.closed = False

    def iter_chunks(self, _size: int) -> Iterator[bytes]:
        for number, piece in enumerate(self.pieces):
            if self.fail_after is not None and number == self.fail_after:
                raise BotoConnectionError(error="connection dropped")
            yield piece

    def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self, body: FakeBody) -> None:
        self.body = body

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Body": self.body, "ContentLength": 6, "ContentType": "application/pdf"}


def use_fake_client(monkeypatch: pytest.MonkeyPatch, body: FakeBody) -> None:
    settings = StorageSettings("http://127.0.0.1:1", "b", "a", "s", "us-east-1", "path")
    monkeypatch.setattr(storage, "_settings_and_client", lambda: (settings, FakeClient(body)))


def test_the_connection_is_released_when_the_reader_stops_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = FakeBody([b"aa", b"bb", b"cc"])
    use_fake_client(monkeypatch, body)
    stored = open_object("k")

    assert next(stored.chunks) == b"aa"
    stored.chunks.close()  # what happens when a download is abandoned

    assert body.closed is True


def test_the_connection_is_released_after_the_last_piece(monkeypatch: pytest.MonkeyPatch) -> None:
    body = FakeBody([b"aa", b"bb"])
    use_fake_client(monkeypatch, body)

    assert b"".join(open_object("k").chunks) == b"aabb"

    assert body.closed is True


def test_a_connection_that_drops_mid_download_is_reported_and_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = FakeBody([b"aa", b"bb"], fail_after=1)
    use_fake_client(monkeypatch, body)
    stored = open_object("k")

    with pytest.raises(StorageUnavailable):
        list(stored.chunks)

    assert body.closed is True
