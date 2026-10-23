"""Connection settings that keep health checks from hanging (operations.md: no unbounded waits)."""

from typing import Any

import psycopg
import pytest
from sqlalchemy.exc import OperationalError

from app.db import get_engine


@pytest.fixture(autouse=True)
def fresh_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:5433/db")
    get_engine.cache_clear()


def test_connecting_to_an_unreachable_database_gives_up_quickly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Without a connect timeout, /health would hang instead of answering 503 when Postgres is down,
    # and the deploy pipeline's smoke test would wait with it. Capture what the driver is given.
    received: dict[str, Any] = {}

    def fake_connect(*args: Any, **kwargs: Any) -> None:
        received.update(kwargs)
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(psycopg, "connect", fake_connect)

    with pytest.raises(OperationalError):
        get_engine().connect()

    assert 0 < int(received["connect_timeout"]) <= 10
