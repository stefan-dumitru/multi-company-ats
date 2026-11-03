from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import get_database_url

# Without explicit names the database invents them, and a later migration cannot refer to a
# constraint it cannot name. With this convention every name is predictable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Parent of every model class."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


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
