"""The Google Calendar settings: all or none, checked when read, never printed.

Without them the app runs exactly as it did before Phase 7's calendar; only the calendar routes say
it is not set up (functional.md > Schedule an interview).
"""

import pytest
from cryptography.fernet import Fernet

from app.config import get_google_settings

NAMES = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "TOKEN_ENCRYPTION_KEY")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_BASE_URL", "https://ats.test")


def set_all(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> str:
    key = Fernet.generate_key().decode()
    values = {
        "GOOGLE_CLIENT_ID": "client-id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "very-secret-client-secret",
        "TOKEN_ENCRYPTION_KEY": key,
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return key


def test_no_settings_means_the_calendar_is_simply_not_set_up() -> None:
    assert get_google_settings() is None


def test_all_three_settings_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    key = set_all(monkeypatch)

    settings = get_google_settings()

    assert settings is not None
    assert settings.client_id == "client-id.apps.googleusercontent.com"
    assert settings.client_secret == "very-secret-client-secret"
    assert settings.encryption_key == key


def test_the_return_address_is_the_sites_own(monkeypatch: pytest.MonkeyPatch) -> None:
    set_all(monkeypatch)

    settings = get_google_settings()

    assert settings is not None
    assert settings.redirect_uri == "https://ats.test/api/calendar/callback"


@pytest.mark.parametrize("missing", NAMES)
def test_some_but_not_all_is_a_mistake_that_stops_the_program(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    set_all(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(RuntimeError, match=missing):
        get_google_settings()


def test_blank_values_count_as_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in NAMES:
        monkeypatch.setenv(name, "   ")

    assert get_google_settings() is None


@pytest.mark.parametrize("bad_key", ["not-a-key", "short", "a" * 44, "é" * 44])
def test_a_key_that_is_not_a_real_encryption_key_is_refused(
    monkeypatch: pytest.MonkeyPatch, bad_key: str
) -> None:
    set_all(monkeypatch, TOKEN_ENCRYPTION_KEY=bad_key)

    with pytest.raises(RuntimeError, match="TOKEN_ENCRYPTION_KEY"):
        get_google_settings()


def test_the_secrets_never_appear_in_a_printout(monkeypatch: pytest.MonkeyPatch) -> None:
    key = set_all(monkeypatch)

    settings = get_google_settings()

    shown = repr(settings) + str(settings)
    assert "very-secret-client-secret" not in shown and key not in shown
