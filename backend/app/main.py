import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.permissions import public_route
from app.config import get_secret_key, get_static_dir
from app.db import get_db
from app.error_handlers import add_error_handlers
from app.frontend import mount_frontend
from app.routers import auth, companies, invitations, users
from app.worker.heartbeat import worker_is_alive
from app.worker.status import recent_failure_count

logger = logging.getLogger(__name__)

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Fail at startup, not on the first invitation: without the key the health check never passes
    # and the deploy is stopped (and rolled back) before users see anything.
    get_secret_key()
    yield


app = FastAPI(title="ATS", lifespan=lifespan)
add_error_handlers(app)
app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(invitations.router)
app.include_router(users.router)


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


def get_known_revisions() -> set[str]:
    """Every migration that exists in the code."""
    scripts = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    return {script.revision for script in scripts.walk_revisions()}


# Both endpoints are deliberately unauthenticated (the deploy pipeline and the platform call them)
# and return only a status word: no versions, hostnames or error text.
@app.get("/health", dependencies=[Depends(public_route)])
def health(db: Session = Depends(get_db)) -> JSONResponse:
    """200 only if the process is up and the database answers."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # Full detail goes to the server log; the client gets a generic answer.
        logger.exception("Health check failed: database unreachable")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


@app.get("/ready", dependencies=[Depends(public_route)])
def ready(
    head: str | None = Depends(get_head_revision),
    applied: str | None = Depends(get_applied_revision),
    known: set[str] = Depends(get_known_revisions),
) -> JSONResponse:
    """200 only if the database has every migration the code expects.

    A database *ahead* of the code (a migration this version has never heard of) is fine: that is
    what a rollback to an older image looks like, and migrations are backward-compatible.
    """
    if head is None or applied is None:
        return JSONResponse({"status": "not ready"}, status_code=503)
    if applied != head and applied in known:
        return JSONResponse({"status": "not ready"}, status_code=503)  # known but behind
    return JSONResponse({"status": "ready"})


@app.get("/health/worker", dependencies=[Depends(public_route)])
def worker_health(
    deployment: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """200 only if the background worker has checked in within the last minute.

    `?deployment=<id>` narrows that to one deployment's worker: the release pipeline uses it to
    prove the *new* worker is running, not just that the old one's last heartbeat is recent.
    """
    try:
        alive = worker_is_alive(db, datetime.now(UTC), deployment)
    except SQLAlchemyError:
        logger.exception("Worker health check failed: database unreachable")
        alive = False
    if not alive:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


@app.get("/health/jobs", dependencies=[Depends(public_route)])
def jobs_health(
    since_minutes: int = Query(ge=1, le=1440),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """200 if no background job gave up for good in the last `since_minutes`, otherwise 503.

    The scheduled monitor calls this. It answers with a count only: it is a public route, so it
    must not reveal job ids, types, errors or addresses.
    """
    try:
        failed = recent_failure_count(db, datetime.now(UTC), timedelta(minutes=since_minutes))
    except SQLAlchemyError:
        logger.exception("Job health check failed: database unreachable")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    if failed:
        return JSONResponse({"status": "failing", "failed": failed}, status_code=503)
    return JSONResponse({"status": "ok", "failed": 0})


# Must stay the last registration in this file: see mount_frontend.
static_dir = get_static_dir()
if static_dir is not None:
    mount_frontend(app, static_dir)
