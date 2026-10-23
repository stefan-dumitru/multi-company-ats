import logging
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_static_dir
from app.db import get_db
from app.frontend import mount_frontend

logger = logging.getLogger(__name__)

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

app = FastAPI(title="ATS")


def get_head_revision() -> str | None:
    """The newest migration that exists in the code."""
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()


def get_applied_revision(db: Session = Depends(get_db)) -> str | None:
    """The migration the database is currently at.

    None means "not ready" for either reason: no migration applied yet, or the database is down.
    """
    try:
        return MigrationContext.configure(db.connection()).get_current_revision()
    except SQLAlchemyError:
        logger.exception("Readiness check failed: could not read the applied migration")
        return None


# Both endpoints are deliberately unauthenticated (the deploy pipeline and the platform call them)
# and return only a status word: no versions, hostnames or error text.
@app.get("/health")
def health(db: Session = Depends(get_db)) -> JSONResponse:
    """200 only if the process is up and the database answers."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Full detail goes to the server log; the client gets a generic answer.
        logger.exception("Health check failed: database unreachable")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


@app.get("/ready")
def ready(
    head: str | None = Depends(get_head_revision),
    applied: str | None = Depends(get_applied_revision),
) -> JSONResponse:
    """200 only if the database has every migration the code expects."""
    if head is None or applied != head:
        return JSONResponse({"status": "not ready"}, status_code=503)
    return JSONResponse({"status": "ready"})


# Must stay the last registration in this file: see mount_frontend.
static_dir = get_static_dir()
if static_dir is not None:
    mount_frontend(app, static_dir)
