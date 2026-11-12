"""The storage settings (operations.md > Environments & Configuration): optional at startup, but a
half-finished setup or an unsafe address is refused with a clear message."""

import pytest

from app.config import get_storage_settings

ALL = {
    "S3_ENDPOINT_URL": "https://storage.example.com",
    "S3_BUCKET": "ats-resumes",
    "S3_ACCESS_KEY_ID": "an-access-key",
    "S3_SECRET_ACCESS_KEY": "a-secret-key",
}
EVERYTHING = [*ALL, "S3_REGION", "S3_ADDRESSING_STYLE"]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in EVERYTHING:
        monkeypatch.delenv(name, raising=False)


def configure(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, value in {**ALL, **overrides}.items():
        monkeypatch.setenv(name, value)


def test_nothing_set_means_no_storage_and_no_error() -> None:
    assert get_storage_settings() is None


def test_blank_values_count_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ALL:
        monkeypatch.setenv(name, "   ")

    assert get_storage_settings() is None


def test_everything_set_gives_the_settings_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)

    settings = get_storage_settings()

    assert settings is not None
    assert settings.endpoint_url == "https://storage.example.com"
    assert settings.bucket == "ats-resumes"
    assert settings.access_key_id == "an-access-key"
    assert settings.secret_access_key == "a-secret-key"
    assert settings.region == "us-east-1"
    assert settings.addressing_style == "path"


def test_region_and_addressing_style_can_be_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, S3_REGION="eu-west-1", S3_ADDRESSING_STYLE="Virtual")

    settings = get_storage_settings()

    assert settings is not None
    assert settings.region == "eu-west-1" and settings.addressing_style == "virtual"


def test_values_are_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, S3_ACCESS_KEY_ID="  key  ", S3_ENDPOINT_URL=" https://s.example.com/ ")

    settings = get_storage_settings()

    assert settings is not None
    assert settings.access_key_id == "key"
    assert settings.endpoint_url == "https://s.example.com"


@pytest.mark.parametrize("missing", list(ALL))
def test_some_but_not_all_is_a_mistake_that_names_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    configure(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(RuntimeError, match=missing):
        get_storage_settings()


def test_the_secret_is_not_in_the_printed_form(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch)

    settings = get_storage_settings()

    assert "a-secret-key" not in repr(settings)


@pytest.mark.parametrize(
    "endpoint",
    [
        "storage.example.com",  # no scheme
        "ftp://storage.example.com",
        "https://",
        "https://storage.example.com/some/path",
        "https://storage.example.com?x=1",
        "https://storage .example.com",
    ],
)
def test_a_bad_endpoint_is_refused(monkeypatch: pytest.MonkeyPatch, endpoint: str) -> None:
    configure(monkeypatch, S3_ENDPOINT_URL=endpoint)

    with pytest.raises(RuntimeError, match="S3_ENDPOINT_URL"):
        get_storage_settings()


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:9000", "http://localhost:9000"])
def test_plain_http_is_allowed_only_to_this_machine(
    monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    configure(monkeypatch, S3_ENDPOINT_URL=endpoint)

    assert get_storage_settings() is not None


def test_plain_http_to_another_machine_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, S3_ENDPOINT_URL="http://storage.example.com")

    with pytest.raises(RuntimeError, match="https"):
        get_storage_settings()


@pytest.mark.parametrize("bucket", ["A", "ab", "Has Space", "UPPER", "-bad", "bad-", "x" * 64])
def test_a_bad_bucket_name_is_refused(monkeypatch: pytest.MonkeyPatch, bucket: str) -> None:
    configure(monkeypatch, S3_BUCKET=bucket)

    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        get_storage_settings()


def test_an_unknown_addressing_style_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    configure(monkeypatch, S3_ADDRESSING_STYLE="sideways")

    with pytest.raises(RuntimeError, match="S3_ADDRESSING_STYLE"):
        get_storage_settings()
