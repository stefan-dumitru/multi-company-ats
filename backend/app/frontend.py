from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope


def is_client_side_route(path: str) -> bool:
    """Whether an unknown path should be answered with the app, for its router to handle.

    `path` is relative, without the leading slash ("login", "api/nope", "assets/app.js"). Starlette
    builds it with the operating system's separator, so on Windows it arrives as "api\\nope".
    """
    path = path.replace("\\", "/")
    if path == "api" or path.startswith("api/"):
        return False  # a mistyped API call must fail visibly, not return an HTML page
    last_segment = path.rsplit("/", 1)[-1]
    return "." not in last_segment  # a missing script, image or stylesheet is a real 404


class SinglePageAppFiles(StaticFiles):
    """Static files that fall back to index.html for the app's own URLs (/login, /users, ...).

    The browser asks the server for those URLs on a refresh or a pasted link, but only the React
    router inside index.html knows what they are.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or not is_client_side_route(path):
                raise
            return await super().get_response("index.html", scope)


def mount_frontend(app: FastAPI, directory: Path) -> None:
    """Serve the built React app from the same origin as the API.

    Call this after every API route is registered: the mount at "/" matches everything, so routes
    added later would be unreachable.
    """
    if not directory.is_dir():
        # Fail at startup instead of serving an API with no UI.
        raise RuntimeError(f"STATIC_DIR is set to {directory}, which is not a directory.")
    # html=True serves index.html for "/".
    app.mount("/", SinglePageAppFiles(directory=directory, html=True), name="frontend")
