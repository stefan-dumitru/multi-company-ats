from datetime import datetime

from pydantic import BaseModel


class CalendarStatusOut(BaseModel):
    # Whether the server has Google set up at all, so the screen can say so instead of failing.
    configured: bool
    connected: bool
    connected_at: datetime | None


class ConnectOut(BaseModel):
    """Where to send the browser: Google's consent window."""

    url: str
