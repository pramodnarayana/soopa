"""
Shell-level Exception Handlers.

These are the cross-cutting exception handlers for the Unified API Shell.
They register framework validation/unhandled exception handlers and Core Platform (UCP)
domain exception handlers without coupling the Shell to any business bounded context.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ucp.domain.exceptions import (
    IdentityProviderPortError,
    ResourceNotFoundError,
    StateConflictError,
)

logger = structlog.get_logger(__name__)


def _sanitize_path(request: Request) -> str:
    return request.url.path.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def _register_framework_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        sanitized_errors = []
        for error in errors:
            error_dict = dict(error)
            error_dict.pop("input", None)
            error_dict.pop("url", None)
            ctx = error_dict.pop("ctx", None)
            if ctx:
                error_dict["ctx"] = {k: str(v) for k, v in ctx.items()}
            sanitized_errors.append(error_dict)

        sanitized_path = _sanitize_path(request)
        logger.error(
            "request_validation_error", path=sanitized_path, validation_errors=sanitized_errors
        )
        return JSONResponse(
            status_code=422,
            content={"detail": sanitized_errors},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.exception("unhandled_exception", path=sanitized_path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )


def _register_ucp_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ResourceNotFoundError)
    async def resource_not_found_exception_handler(
        request: Request, exc: ResourceNotFoundError
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.error("resource_not_found", path=sanitized_path, error=str(exc))
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    @app.exception_handler(IdentityProviderPortError)
    async def identity_provider_exception_handler(
        request: Request, exc: IdentityProviderPortError
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.error("identity_provider_error", path=sanitized_path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal identity provider error occurred."},
        )

    @app.exception_handler(StateConflictError)
    async def state_conflict_exception_handler(
        request: Request, exc: StateConflictError
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.error("state_conflict", path=sanitized_path, error=str(exc))
        return JSONResponse(status_code=409, content={"detail": str(exc)})


def setup_shell_exception_handlers(app: FastAPI) -> None:
    """
    Registers framework and Core Platform (UCP) exception handlers on the Shell (Host) application.
    """
    _register_framework_exception_handlers(app)
    _register_ucp_exception_handlers(app)
