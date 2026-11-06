"""Email settings (operations.md > External Integrations): a wrong or missing setting must stop
the program with a message naming it, not surface later as a mysterious failed job."""

import pytest

from app.config import SmtpSettings, get_app_base_url, get_smtp_settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_STARTTLS",
        "EMAIL_FROM",
        "APP_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def set_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "mail.internal")
    monkeypatch.setenv("EMAIL_FROM", "ATS <no-reply@example.test>")


# ---- SMTP ---------------------------------------------------------------------------------


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    set_minimal(monkeypatch)
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_STARTTLS", "false")

    assert get_smtp_settings() == SmtpSettings(
        host="mail.internal",
        port=1025,
        username=None,
        password=None,
        starttls=False,
        sender="ATS <no-reply@example.test>",
    )


def test_encryption_is_on_and_the_port_is_587_unless_told_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_minimal(monkeypatch)

    settings = get_smtp_settings()

    assert settings.starttls is True
    assert settings.port == 587


@pytest.mark.parametrize("missing", ["SMTP_HOST", "EMAIL_FROM"])
def test_a_missing_required_setting_names_itself(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    set_minimal(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(RuntimeError, match=missing):
        get_smtp_settings()


@pytest.mark.parametrize("bad", ["abc", "0", "70000", ""])
def test_a_nonsense_port_is_refused(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    set_minimal(monkeypatch)
    monkeypatch.setenv("SMTP_PORT", bad)

    with pytest.raises(RuntimeError, match="SMTP_PORT"):
        get_smtp_settings()


def test_credentials_are_never_sent_over_an_unencrypted_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_minimal(monkeypatch)
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("SMTP_STARTTLS", "false")

    with pytest.raises(RuntimeError, match="SMTP_STARTTLS"):
        get_smtp_settings()


def test_a_username_needs_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    set_minimal(monkeypatch)
    monkeypatch.setenv("SMTP_USERNAME", "user")

    with pytest.raises(RuntimeError, match="SMTP_PASSWORD"):
        get_smtp_settings()


def test_the_sender_must_be_a_single_plain_address(monkeypatch: pytest.MonkeyPatch) -> None:
    set_minimal(monkeypatch)
    monkeypatch.setenv("EMAIL_FROM", "not an address")

    with pytest.raises(RuntimeError, match="EMAIL_FROM"):
        get_smtp_settings()


def test_the_password_is_not_shown_when_settings_are_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_minimal(monkeypatch)
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "very-secret-value")

    assert "very-secret-value" not in repr(get_smtp_settings())


# ---- the public address used in links -----------------------------------------------------


def test_the_base_url_loses_a_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_BASE_URL", "https://ats.example.test/")

    assert get_app_base_url() == "https://ats.example.test"


def test_a_missing_base_url_names_itself() -> None:
    with pytest.raises(RuntimeError, match="APP_BASE_URL"):
        get_app_base_url()


def test_links_over_plain_http_are_refused_except_for_the_developers_own_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_BASE_URL", "http://ats.example.test")
    with pytest.raises(RuntimeError, match="APP_BASE_URL"):
        get_app_base_url()

    monkeypatch.setenv("APP_BASE_URL", "http://127.0.0.1:5173")
    assert get_app_base_url() == "http://127.0.0.1:5173"


@pytest.mark.parametrize(
    "bad", ["ats.example.test", "ftp://x.test", "https://", "https://a b.test"]
)
def test_a_base_url_that_is_not_a_web_address_is_refused(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("APP_BASE_URL", bad)

    with pytest.raises(RuntimeError, match="APP_BASE_URL"):
        get_app_base_url()
