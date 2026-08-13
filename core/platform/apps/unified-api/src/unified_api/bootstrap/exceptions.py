"""
Shell-level Exception Handlers.

These are the cross-cutting exception handlers for the Unified API Shell.
They aggregate exception types from all domains into a single, consistent
error response contract for every client of the public API.

Architecture note:
  - This module is part of the Shell (Host) — the ONLY component that is
    allowed to import from both UCP and EDI simultaneously.
  - Domain-specific exception handlers registered inside sub-apps (e.g.
    edi_app's own OrchestrationError handler) take precedence for requests
    that Starlette dispatches to the EDI sub-app, because inner-scope handlers
    are invoked first. These Shell-level handlers act as a backstop for
    exceptions that propagate out of any mounted sub-app.
  - UCP exceptions (e.g. IdentityProviderError) are only registered here since
    UCP routers are inlined on the Shell, not a sub-app.
"""

import structlog
from edi.core.exceptions import OrchestrationError, VaultError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ucp.core.exceptions import IdentityProviderError

logger = structlog.get_logger(__name__)


def setup_shell_exception_handlers(app: FastAPI) -> None:
    """
    Registers all exception handlers on the Shell (Host) application.

    Covers:
      - UCP domain exceptions (IdentityProviderError)
      - EDI domain exceptions (OrchestrationError, VaultError) — backstop only
      - Framework validation exceptions (RequestValidationError)
    """

    @app.exception_handler(IdentityProviderError)
    async def identity_provider_exception_handler(
        request: Request, exc: IdentityProviderError
    ) -> JSONResponse:
        logger.error("IdentityProviderError at %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal identity provider error occurred."},
        )

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

        logger.error("422 Error at %s: %s", request.url.path, sanitized_errors)
        return JSONResponse(
            status_code=422,
            content={"detail": sanitized_errors},
        )

    @app.exception_handler(OrchestrationError)
    async def orchestration_exception_handler(
        request: Request, exc: OrchestrationError
    ) -> JSONResponse:
        logger.error("OrchestrationError at %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )

    @app.exception_handler(VaultError)
    async def vault_exception_handler(request: Request, exc: VaultError) -> JSONResponse:
        logger.error("VaultError at %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )
