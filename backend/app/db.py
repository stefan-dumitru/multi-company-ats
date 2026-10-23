from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_database_url


class Base(DeclarativeBase):
    """Parent of every model class (added from Phase 2 on)."""


@lru_cache
def get_engine() -> Engine:
    # Built on first use rather than at import time, so importing the app (and running tests that
    # replace get_db) never needs a database.
    # connect_timeout: never wait indefinitely for an unreachable database, so /health can answer
    # 503 promptly and the pipeline's smoke test fails fast instead of hanging.
    return create_engine(
        get_database_url(), pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )


def get_db() -> Iterator[Session]:
    """One session per request, always closed afterwards."""
    with Session(get_engine()) as session:
        yield session
