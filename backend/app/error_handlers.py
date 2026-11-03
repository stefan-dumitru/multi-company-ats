from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.errors import NotFoundError


def not_found_handler(_request: Request, _error: Exception) -> JSONResponse:
    # Same body whether the row never existed or belongs to another company.
    return JSONResponse({"detail": "Not found."}, status_code=404)


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, not_found_handler)
