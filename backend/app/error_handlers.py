from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.integrations.storage import StorageNotConfigured, StorageUnavailable
from app.services.errors import EmailNotVerified, NotFoundError, RuleViolation


def not_found_handler(_request: Request, _error: Exception) -> JSONResponse:
    # Same body whether the row never existed or belongs to another company.
    return JSONResponse({"detail": "Not found."}, status_code=404)


def email_not_verified_handler(_request: Request, _error: Exception) -> JSONResponse:
    # The `code` lets the frontend show the "verify your email" screen instead of a generic error.
    return JSONResponse(
        {"detail": "Verify your email first.", "code": "email_not_verified"}, status_code=403
    )


def rule_violation_handler(_request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RuleViolation)
    return JSONResponse(
        {"detail": error.message, "code": error.code}, status_code=error.status_code
    )


def storage_unavailable_handler(_request: Request, _error: Exception) -> JSONResponse:
    # Not set up, or the server is down: the same answer, and the log says which (operations.md).
    return JSONResponse(
        {
            "detail": "File storage is not available. Please try again later.",
            "code": "storage_unavailable",
        },
        status_code=503,
    )


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StorageNotConfigured, storage_unavailable_handler)
    app.add_exception_handler(StorageUnavailable, storage_unavailable_handler)
    app.add_exception_handler(RuleViolation, rule_violation_handler)
    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(EmailNotVerified, email_not_verified_handler)
