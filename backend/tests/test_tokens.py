"""Signed links (security.md > Authentication): a link is `<row id>.<signature>`.

The queue and the database hold only the row id; the worker recomputes the link from it. Rules under
test: only we can make a valid link; a link works for one purpose only; garbage never crashes the
check; changing the server key invalidates every outstanding link.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import tokens
from app.config import get_secret_key
from app.main import app

ROW_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


# ---- the signing key ----------------------------------------------------------------------


def test_the_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "a" * 40)

    assert get_secret_key() == "a" * 40


def test_a_missing_key_stops_the_program_naming_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        get_secret_key()


def test_a_short_key_is_refused_because_it_would_be_guessable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "short")

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        get_secret_key()


def test_the_web_app_refuses_to_start_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Better to fail at deploy time (the health check never passes) than on the first invitation.
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY"), TestClient(app):
        pass


# ---- making and reading links -------------------------------------------------------------


def test_a_link_reads_back_to_the_row_it_was_made_for() -> None:
    token = tokens.make_token(tokens.INVITATION, ROW_ID)

    assert tokens.read_token(tokens.INVITATION, token) == ROW_ID


def test_the_same_row_always_gets_the_same_link() -> None:
    # The worker has to be able to rebuild the link the web request promised.
    assert tokens.make_token(tokens.INVITATION, ROW_ID) == tokens.make_token(
        tokens.INVITATION, ROW_ID
    )


def test_the_link_does_not_contain_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "m" * 40)

    token = tokens.make_token(tokens.INVITATION, ROW_ID)

    assert "mmmm" not in token  # the key's own characters are not in the link


def test_a_link_for_one_purpose_does_not_work_for_another() -> None:
    # A password-reset link must not be usable as an invitation, and vice versa.
    token = tokens.make_token(tokens.PASSWORD_RESET, ROW_ID)

    assert tokens.read_token(tokens.INVITATION, token) is None
    assert tokens.read_token(tokens.PASSWORD_RESET, token) == ROW_ID


def test_different_rows_get_different_links() -> None:
    other = uuid.uuid4()

    assert tokens.make_token(tokens.INVITATION, ROW_ID) != tokens.make_token(
        tokens.INVITATION, other
    )


def test_a_link_with_another_rows_id_is_refused() -> None:
    # Swap the id for someone else's but keep the signature: this is the forgery attempt.
    token = tokens.make_token(tokens.INVITATION, ROW_ID)
    signature = token.split(".", 1)[1]
    forged = f"{uuid.uuid4()}.{signature}"

    assert tokens.read_token(tokens.INVITATION, forged) is None


def test_a_link_with_a_changed_signature_is_refused() -> None:
    token = tokens.make_token(tokens.INVITATION, ROW_ID)
    flipped = token[:-1] + ("0" if token[-1] != "0" else "1")

    assert tokens.read_token(tokens.INVITATION, flipped) is None


def test_changing_the_server_key_invalidates_every_link(monkeypatch: pytest.MonkeyPatch) -> None:
    token = tokens.make_token(tokens.INVITATION, ROW_ID)

    monkeypatch.setenv("SECRET_KEY", "z" * 40)

    assert tokens.read_token(tokens.INVITATION, token) is None


@pytest.mark.parametrize(
    "garbage",
    [
        "",
        "abc",
        ".",
        "..",
        "not-a-uuid.abcdef",
        f"{ROW_ID}.",
        f".{'a' * 64}",
        f"{ROW_ID}.{'z' * 64}",
        f"{ROW_ID}.{'a' * 64}.extra",
        "x" * 5000,
        "\x00" * 10,
        "é.é",
    ],
)
def test_garbage_is_refused_without_crashing(garbage: str) -> None:
    assert tokens.read_token(tokens.INVITATION, garbage) is None
