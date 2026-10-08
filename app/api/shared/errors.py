"""Shared exception handlers for cross-cutting API errors."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ...application.idempotency import IdempotencyConflictError


async def _handle_idempotency_conflict(
    request: Request,
    exc: IdempotencyConflictError,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                "details": exc.details,
                "request_id": request_id,
            }
        },
    )


def register_shared_exception_handlers(app) -> None:
    app.add_exception_handler(IdempotencyConflictError, _handle_idempotency_conflict)


__all__ = ["register_shared_exception_handlers"]
