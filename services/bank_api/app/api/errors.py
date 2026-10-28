"""Turns exceptions into consistent JSON error responses.

Every error looks like: {"error": {"code": "...", "message": "..."}}
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """Our own errors: use the status and code the exception carries."""
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Bad request bodies. FastAPI's default echoes the input back, which
    could be a PIN, so we keep only where the problem is and what it is."""
    assert isinstance(exc, RequestValidationError)
    problems = [
        {"field": ".".join(str(part) for part in err["loc"]), "problem": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": "The request is missing something or has a bad value.",
                "problems": problems,
            }
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach both handlers to the app."""
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
