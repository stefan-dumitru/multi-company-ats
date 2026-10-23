from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: Path) -> None:
    """Serve the built React app from the same origin as the API.

    Call this after every API route is registered: the mount at "/" matches everything, so routes
    added later would be unreachable.
    """
    if not directory.is_dir():
        # Fail at startup instead of serving an API with no UI.
        raise RuntimeError(f"STATIC_DIR is set to {directory}, which is not a directory.")
    # html=True serves index.html for "/". Unknown paths stay 404 (no catch-all SPA fallback yet:
    # it is only needed once the app has client-side routes, which arrive with the first UI phase).
    app.mount("/", StaticFiles(directory=directory, html=True), name="frontend")
