"""Entry point: `python -m app.worker` runs the worker; `python -m app.worker status` reports."""

import argparse
import logging
import signal
import threading
from datetime import UTC, datetime
from types import FrameType

from sqlalchemy.orm import Session

from app.config import (
    get_app_base_url,
    get_deployment_id,
    get_secret_key,
    get_smtp_settings,
)
from app.db import get_engine
from app.logging import configure_logging
from app.worker.handlers import HANDLERS
from app.worker.runner import run_loop
from app.worker.status import format_status

logger = logging.getLogger("ats.worker")


def run_worker() -> None:
    stop = threading.Event()

    def ask_to_stop(signal_number: int, _frame: FrameType | None) -> None:
        # Railway sends SIGTERM on every deploy. Only set a flag: the loop finishes the current job.
        logger.info("stop requested", extra={"signal": signal.Signals(signal_number).name})
        stop.set()

    signal.signal(signal.SIGTERM, ask_to_stop)
    signal.signal(signal.SIGINT, ask_to_stop)

    # Fail at startup, not on the first email: a worker with wrong mail settings should not look
    # healthy while every email it handles fails.
    get_smtp_settings()
    get_app_base_url()
    get_secret_key()

    logger.info("worker started")
    with Session(get_engine()) as db:
        run_loop(db, stop, HANDLERS, deployment_id=get_deployment_id())
    logger.info("worker stopped")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument(
        "command", nargs="?", choices=["run", "status"], default="run", help="default: run"
    )
    arguments = parser.parse_args()

    if arguments.command == "status":
        with Session(get_engine()) as db:
            print(format_status(db, datetime.now(UTC)))
    else:
        configure_logging()
        run_worker()


if __name__ == "__main__":
    main()
