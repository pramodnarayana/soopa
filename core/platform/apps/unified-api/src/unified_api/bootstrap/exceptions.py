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
  - UCP exceptions (e.g. IdentityProviderPortError) are only registered here since
    UCP routers are inlined on the Shell, not a sub-app.
"""

import structlog
from edi.domain.exceptions import OrchestrationError, VaultError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from ip.domain.exceptions import (
    AuthenticationFailedException,
    ConnectionNotFoundException,
    ConnectorNotFoundException,
    DuplicateConnectionFingerprintException,
    InvalidConnectionStateException,
)
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
        logger.warning("resource_not_found", path=sanitized_path, error=str(exc))
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
        logger.warning("state_conflict", path=sanitized_path, error=str(exc))
        return JSONResponse(status_code=409, content={"detail": str(exc)})


def _register_edi_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(OrchestrationError)
    async def orchestration_exception_handler(
        request: Request, exc: OrchestrationError
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.error("orchestration_error", path=sanitized_path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )

    @app.exception_handler(VaultError)
    async def vault_exception_handler(request: Request, exc: VaultError) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.error("vault_error", path=sanitized_path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )


def _register_ip_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ConnectionNotFoundException)
    async def connection_not_found_handler(
        request: Request, exc: ConnectionNotFoundException
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.warning("connection_not_found", path=sanitized_path, error=str(exc))
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DuplicateConnectionFingerprintException)
    async def duplicate_connection_handler(
        request: Request, exc: DuplicateConnectionFingerprintException
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.warning("duplicate_connection_fingerprint", path=sanitized_path, error=str(exc))
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidConnectionStateException)
    async def invalid_connection_state_handler(
        request: Request, exc: InvalidConnectionStateException
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.warning("invalid_connection_state", path=sanitized_path, error=str(exc))
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ConnectorNotFoundException)
    async def connector_not_found_handler(
        request: Request, exc: ConnectorNotFoundException
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.warning("connector_not_found", path=sanitized_path, error=str(exc))
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AuthenticationFailedException)
    async def auth_failed_handler(
        request: Request, exc: AuthenticationFailedException
    ) -> JSONResponse:
        sanitized_path = _sanitize_path(request)
        logger.warning("authentication_failed", path=sanitized_path, error=str(exc))
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "code": "EXTERNAL_AUTHENTICATION_FAILED"},
        )


def setup_shell_exception_handlers(app: FastAPI) -> None:
    """
    Registers all exception handlers on the Shell (Host) application.

    Covers:
      - Framework validation & unhandled exceptions
      - UCP domain exceptions
      - EDI domain exceptions (backstop only)
      - IP domain exceptions
    """
    _register_framework_exception_handlers(app)
    _register_ucp_exception_handlers(app)
    _register_edi_exception_handlers(app)
    _register_ip_exception_handlers(app)
