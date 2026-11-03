"""Password hashing and rules. Argon2id is deliberately slow and salted: see security.md."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_PASSWORD_LENGTH = 12
# Hashing cost grows with input length, so an absurdly long password is refused up front.
MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher()


class PasswordTooWeak(ValueError):
    """The password breaks a rule; the message is safe to show to the user."""


def check_password_rules(password: str) -> None:
    # Length over symbols: no "must contain a digit" rules (security.md).
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordTooWeak(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordTooWeak(f"Password must be at most {MAX_PASSWORD_LENGTH} characters long.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError, InvalidHashError:
        # A wrong password and a damaged stored hash both mean "do not log in".
        return False
