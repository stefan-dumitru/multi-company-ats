"""Bring the database up to date before a new version starts: `python -m app.migrate`.

This is the pre-deploy command on Railway. It is `alembic upgrade head` with one exception.

If the database is *ahead* of this version of the code (it has a migration this code has never
heard of), `alembic upgrade head` would stop with "Can't locate revision". That is exactly what a
rollback to an older image looks like once a newer release has migrated the database, and it would
block the rollback. The project's rule is that migrations are backward-compatible, so the older
code is written to run against the newer schema; this command therefore skips the migration step
in that case, says so in the deploy log, and lets the old version start.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.config import get_database_url

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

UPGRADED = "upgraded"
UP_TO_DATE = "up to date"
AHEAD = "ahead"


def migrate() -> str:
    """Upgrade the database to this version's head, unless it is already ahead of it."""
    config = Config(str(ALEMBIC_INI))
    known_revisions = {
        script.revision for script in ScriptDirectory.from_config(config).walk_revisions()
    }
    head = ScriptDirectory.from_config(config).get_current_head()

    # connect_timeout: an unreachable database should fail the deploy promptly, not hang it.
    engine = create_engine(get_database_url(), connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()

    if current is not None and current not in known_revisions:
        return AHEAD
    if current == head:
        return UP_TO_DATE
    command.upgrade(config, "head")
    return UPGRADED


def main() -> int:
    outcome = migrate()
    if outcome == AHEAD:
        print(
            "The database is ahead of this version (it has migrations this code does not know). "
            "Skipping migrations; this version is written to work with the newer schema."
        )
    else:
        print(f"Migrations: database {outcome}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
