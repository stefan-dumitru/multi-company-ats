"""`python -m app.migrate`: the pre-deploy step that brings the database up to date.

The rule under test: a database that is *ahead* of this version of the code (which is what a
rollback to an older image looks like) must not stop the old version from starting, because the
code is written to work against the newer schema (operations.md > Database Migrations). Anything
else going wrong must still fail the deploy.
"""

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.migrate import AHEAD, UP_TO_DATE, UPGRADED, main, migrate
from tests.test_migrations import ALEMBIC_INI, empty_database_url  # noqa: F401 (fixture)


def applied_revision(url: str) -> str | None:
    engine = create_engine(url)
    with engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    engine.dispose()
    return revision


def head_revision() -> str:
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    assert head is not None
    return head


def test_an_empty_database_is_brought_up_to_date(empty_database_url: str) -> None:  # noqa: F811
    assert migrate() == UPGRADED
    assert applied_revision(empty_database_url) == head_revision()


def test_a_database_that_is_behind_is_upgraded(empty_database_url: str) -> None:  # noqa: F811
    command.upgrade(Config(str(ALEMBIC_INI)), "0003")

    assert migrate() == UPGRADED
    assert applied_revision(empty_database_url) == head_revision()


def test_a_database_that_is_already_current_is_left_alone(
    empty_database_url: str,  # noqa: F811
) -> None:
    migrate()

    assert migrate() == UP_TO_DATE
    assert applied_revision(empty_database_url) == head_revision()


def test_a_database_ahead_of_this_version_is_left_alone_not_failed(
    empty_database_url: str,  # noqa: F811
) -> None:
    # What an older image sees after a newer release migrated the database and was rolled back.
    migrate()
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    engine.dispose()

    assert migrate() == AHEAD
    assert applied_revision(empty_database_url) == "9999"  # untouched


def test_the_command_succeeds_when_the_database_is_ahead(
    empty_database_url: str,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    migrate()
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    engine.dispose()

    assert main() == 0
    assert "ahead" in capsys.readouterr().out.lower()  # the skip is visible in the deploy log


def test_an_unreachable_database_still_fails_the_deploy(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only "ahead" is forgiven. Not being able to reach the database must stop the release.
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:1/none")

    with pytest.raises(OperationalError):
        main()
