"""Which function handles which job type. Empty until Step 3 adds `send_email`."""

from app.worker.runner import Handler

HANDLERS: dict[str, Handler] = {}
