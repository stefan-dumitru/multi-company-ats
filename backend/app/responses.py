"""HTTP responses that more than one route builds."""

from fastapi.responses import StreamingResponse

from app.integrations import storage
from app.models import File
from app.services.resume_files import content_disposition


def resume_download(file: File, stored: storage.StoredObject) -> StreamingResponse:
    """A resume streamed to the caller. The one place that decides how a resume is delivered,
    so the candidate's own download and the staff download cannot differ."""
    return StreamingResponse(
        stored.chunks,
        media_type=file.content_type,
        headers={
            "Content-Disposition": content_disposition(file.original_filename),
            "Content-Length": str(stored.size),
            # The file is only ever downloaded, never shown by the app, and the browser must not
            # guess a different type from the bytes.
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
