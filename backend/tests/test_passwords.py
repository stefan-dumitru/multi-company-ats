"""Password rules (security.md): 12+ characters, no composition rules, slow hash."""

import pytest

from app.auth.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordTooWeak,
    check_password_rules,
    hash_password,
    verify_password,
)


def test_a_hash_is_not_the_password_and_is_argon2id() -> None:
    hashed = hash_password("correct horse battery")

    assert "correct horse battery" not in hashed
    assert hashed.startswith("$argon2id$")


def test_the_same_password_hashes_differently_each_time() -> None:
    # Each hash carries its own random salt, so two users with one password do not share a hash.
    assert hash_password("correct horse battery") != hash_password("correct horse battery")


def test_the_right_password_verifies_and_a_wrong_one_does_not() -> None:
    hashed = hash_password("correct horse battery")

    assert verify_password(hashed, "correct horse battery") is True
    assert verify_password(hashed, "Correct horse battery") is False
    assert verify_password(hashed, "") is False


def test_a_damaged_hash_is_a_failed_login_not_a_crash() -> None:
    assert verify_password("not-a-real-hash", "whatever password") is False


def test_twelve_characters_is_the_shortest_allowed_password() -> None:
    check_password_rules("a" * MIN_PASSWORD_LENGTH)

    with pytest.raises(PasswordTooWeak, match="12"):
        check_password_rules("a" * (MIN_PASSWORD_LENGTH - 1))


def test_there_are_no_composition_rules() -> None:
    # Length beats symbols: a long lowercase passphrase is fine.
    check_password_rules("just lowercase words here")


def test_very_long_passwords_are_refused_so_hashing_cannot_be_abused() -> None:
    check_password_rules("a" * MAX_PASSWORD_LENGTH)

    with pytest.raises(PasswordTooWeak, match=str(MAX_PASSWORD_LENGTH)):
        check_password_rules("a" * (MAX_PASSWORD_LENGTH + 1))
