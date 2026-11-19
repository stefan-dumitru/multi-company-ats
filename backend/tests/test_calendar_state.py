"""The signed `state` that carries a person through Google's window and back.

It must prove three things when Google sends the browser back: we issued it, it is recent, and it
was issued for the person who is logged in right now. Anything else is refused quietly.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth import tokens

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
MAX_AGE = timedelta(minutes=10)


@pytest.fixture(autouse=True)
def secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "k" * 40)


def test_a_fresh_state_gives_back_the_person_it_was_made_for() -> None:
    person = uuid.uuid4()

    state = tokens.make_state(tokens.GOOGLE_CALENDAR, person, NOW)

    assert (
        tokens.read_state(tokens.GOOGLE_CALENDAR, state, NOW + timedelta(minutes=3), MAX_AGE)
        == person
    )


def test_each_state_is_different_even_for_the_same_person() -> None:
    person = uuid.uuid4()

    first = tokens.make_state(tokens.GOOGLE_CALENDAR, person, NOW)
    second = tokens.make_state(tokens.GOOGLE_CALENDAR, person, NOW + timedelta(seconds=1))

    assert first != second


def test_a_state_that_is_too_old_is_refused() -> None:
    state = tokens.make_state(tokens.GOOGLE_CALENDAR, uuid.uuid4(), NOW)

    assert (
        tokens.read_state(
            tokens.GOOGLE_CALENDAR, state, NOW + MAX_AGE + timedelta(seconds=1), MAX_AGE
        )
        is None
    )


def test_a_state_just_inside_the_limit_still_works() -> None:
    person = uuid.uuid4()
    state = tokens.make_state(tokens.GOOGLE_CALENDAR, person, NOW)

    assert tokens.read_state(tokens.GOOGLE_CALENDAR, state, NOW + MAX_AGE, MAX_AGE) == person


def test_a_state_from_the_future_is_refused() -> None:
    state = tokens.make_state(tokens.GOOGLE_CALENDAR, uuid.uuid4(), NOW + timedelta(hours=1))

    assert tokens.read_state(tokens.GOOGLE_CALENDAR, state, NOW, MAX_AGE) is None


def test_changing_any_part_of_it_makes_it_worthless() -> None:
    person = uuid.uuid4()
    state = tokens.make_state(tokens.GOOGLE_CALENDAR, person, NOW)
    other_person, stamp, signature = state.split(".")

    tampered = [
        f"{uuid.uuid4()}.{stamp}.{signature}",  # someone else's id
        f"{other_person}.{int(stamp) + 1}.{signature}",  # a later time
        f"{other_person}.{stamp}.{signature[:-1]}{'0' if signature[-1] != '0' else '1'}",
        f"{other_person}.{stamp}.",
    ]

    for bad in tampered:
        assert tokens.read_state(tokens.GOOGLE_CALENDAR, bad, NOW, MAX_AGE) is None


def test_a_state_made_for_another_purpose_is_refused() -> None:
    state = tokens.make_state(tokens.PASSWORD_RESET, uuid.uuid4(), NOW)

    assert tokens.read_state(tokens.GOOGLE_CALENDAR, state, NOW, MAX_AGE) is None


def test_a_state_signed_with_another_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    state = tokens.make_state(tokens.GOOGLE_CALENDAR, uuid.uuid4(), NOW)
    monkeypatch.setenv("SECRET_KEY", "z" * 40)

    assert tokens.read_state(tokens.GOOGLE_CALENDAR, state, NOW, MAX_AGE) is None


@pytest.mark.parametrize(
    "garbage", ["", "x", "a.b", "a.b.c", "....", "9" * 300, f"{uuid.uuid4()}.notanumber.sig"]
)
def test_garbage_is_an_ordinary_no_never_an_error(garbage: str) -> None:
    assert tokens.read_state(tokens.GOOGLE_CALENDAR, garbage, NOW, MAX_AGE) is None
