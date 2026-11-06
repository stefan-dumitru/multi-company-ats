"""The worker as a real process: Railway stops it with SIGTERM on every deploy, and it must exit
cleanly (code 0) rather than be killed mid-job.

Linux/macOS only: Windows has no SIGTERM to send. CI runs on Linux, so this is checked on every PR.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.worker import heartbeat

BACKEND_DIR = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot send SIGTERM")


def test_sigterm_stops_the_worker_cleanly(db: Session, migrated_database_url: str) -> None:
    environment = {**os.environ, "DATABASE_URL": migrated_database_url}
    process = subprocess.Popen(
        [sys.executable, "-m", "app.worker"],
        cwd=BACKEND_DIR,
        env=environment,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        # Wait until it is really running (its first heartbeat), not just launched.
        deadline = time.monotonic() + 20
        while heartbeat.last_heartbeat(db) is None:
            assert time.monotonic() < deadline, "the worker never checked in"
            assert process.poll() is None, "the worker exited before checking in"
            db.rollback()  # see the other process's committed row, not our old snapshot
            time.sleep(0.2)

        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()

    assert process.returncode == 0
    assert "worker stopped" in output
