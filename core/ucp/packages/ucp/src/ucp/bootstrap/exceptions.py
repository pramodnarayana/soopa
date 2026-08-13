"""
UCP Domain Exception Handlers.

Registers HTTP exception handlers for exceptions raised within the UCP
bounded context.

Architecture note:
  - Only UCP-domain exceptions belong here. Cross-domain exceptions
    (e.g. EDI's OrchestrationError, VaultError) are registered on the
    Shell (unified_api/bootstrap/exceptions.py), which is the only layer
    allowed to import from multiple domains simultaneously.
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ucp.core.exceptions import IdentityProviderError, ResourceNotFoundError

logger = structlog.get_logger(__name__)


def setup_exception_handlers(app: FastAPI) -> None:
    """
    Registers UCP-domain exception handlers on the given application.

    NOTE: When UCP routers are inlined on the Shell (not a sub-app), this
    function should NOT be called — use
    ``unified_api.bootstrap.exceptions.setup_shell_exception_handlers``
    instead, which covers all domains.
    """

    @app.exception_handler(ResourceNotFoundError)
    async def resource_not_found_exception_handler(
        request: Request, exc: ResourceNotFoundError
    ) -> JSONResponse:
        logger.warning("ResourceNotFoundError at %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

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
