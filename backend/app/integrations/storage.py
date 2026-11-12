"""Object storage for files (resumes). S3-compatible: a Railway bucket live, a small stand-in server
locally and in CI.

Three calls (put, open, delete) and three errors. Nothing else in the app talks to boto3, so the
rules that matter live here once: explicit timeouts, no inline retries (retries belong to the
background worker), and errors that never carry a secret.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import StorageSettings, get_storage_settings

logger = logging.getLogger(__name__)

# Never wait indefinitely (operations.md > External Services).
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 10
CHUNK_SIZE = 64 * 1024
# What S3-compatible servers answer for a key that is not there.
NOT_FOUND_CODES = {"NoSuchKey", "NotFound", "404"}


class StorageError(Exception):
    """Base for everything this module raises."""


class StorageNotConfigured(StorageError):
    """No (or only part of the) storage settings are set. The app starts without them."""


class StorageUnavailable(StorageError):
    """The storage server could not be reached or refused the request."""


class ObjectNotFound(StorageError):
    """There is no object under that key."""


@dataclass
class StoredObject:
    size: int
    content_type: str
    # The bytes, in pieces. Consume it fully or close it; the connection is released either way.
    chunks: Iterator[bytes]


@lru_cache(maxsize=4)
def client_for(settings: StorageSettings) -> Any:
    """The S3 client for these settings, made once and reused."""
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name=settings.region,
        config=Config(
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            read_timeout=READ_TIMEOUT_SECONDS,
            retries={"max_attempts": 0},
            s3={"addressing_style": settings.addressing_style},
            # Newer boto3 adds checksum trailers by default, which several S3-compatible servers
            # reject. Only send or check them when the server requires it.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _settings_and_client() -> tuple[StorageSettings, Any]:
    try:
        settings = get_storage_settings()
    except RuntimeError as error:  # part of the settings is set: a mistake worth a clear message
        logger.error("Storage settings are incomplete: %s", error)
        raise StorageNotConfigured(str(error)) from error
    if settings is None:
        raise StorageNotConfigured("File storage is not configured.")
    return settings, client_for(settings)


def _unavailable(operation: str, error: Exception) -> StorageUnavailable:
    # Log what kind of failure it was, never the request (it carries the object key and headers).
    if isinstance(error, ClientError):
        reason = str(error.response.get("Error", {}).get("Code", "unknown"))
    else:
        reason = type(error).__name__
    logger.error("Storage %s failed: %s", operation, reason)
    return StorageUnavailable("File storage is not available.")


def _is_not_found(error: ClientError) -> bool:
    return str(error.response.get("Error", {}).get("Code", "")) in NOT_FOUND_CODES


def put_object(key: str, data: bytes, content_type: str) -> None:
    """Store `data` under `key`, replacing anything already there."""
    settings, client = _settings_and_client()
    try:
        client.put_object(Bucket=settings.bucket, Key=key, Body=data, ContentType=content_type)
    except (ClientError, BotoCoreError) as error:
        raise _unavailable("put", error) from error


def open_object(key: str) -> StoredObject:
    """Start reading the object under `key`. Raises ObjectNotFound before any byte is sent."""
    settings, client = _settings_and_client()
    try:
        response = client.get_object(Bucket=settings.bucket, Key=key)
    except ClientError as error:
        if _is_not_found(error):
            raise ObjectNotFound(key) from error
        raise _unavailable("get", error) from error
    except BotoCoreError as error:
        raise _unavailable("get", error) from error
    return StoredObject(
        size=int(response["ContentLength"]),
        content_type=str(response.get("ContentType") or "application/octet-stream"),
        chunks=_read_in_chunks(response["Body"]),
    )


def _read_in_chunks(body: Any) -> Iterator[bytes]:
    try:
        yield from body.iter_chunks(CHUNK_SIZE)
    except (ClientError, BotoCoreError) as error:
        raise _unavailable("read", error) from error
    finally:
        body.close()  # also when the caller stops early or the client disconnects


def delete_object(key: str) -> None:
    """Remove the object under `key`. Removing one that is not there is not an error."""
    settings, client = _settings_and_client()
    try:
        client.delete_object(Bucket=settings.bucket, Key=key)
    except ClientError as error:
        if not _is_not_found(error):
            raise _unavailable("delete", error) from error
    except BotoCoreError as error:
        raise _unavailable("delete", error) from error
