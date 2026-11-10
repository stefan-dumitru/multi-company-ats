from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RuleViolation, rule_violation_handler)
    app.add_exception_handler(NotFoundError, not_found_handler)
    app.add_exception_handler(EmailNotVerified, email_not_verified_handler)
