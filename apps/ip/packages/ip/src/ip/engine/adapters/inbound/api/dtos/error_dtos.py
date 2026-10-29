"""Standardized RFC 7807 HTTP error response DTOs for the Integration Platform API."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.responses import JSONResponse
from ip.engine.domain.exceptions import IpError
from pydantic import BaseModel, Field


class ErrorDetailHttpResponse(BaseModel):
    """Granular field-level or parameter-level validation or business rule violation."""

    field: str | None = Field(
        None, description="Request field that caused the error, if applicable"
    )
    code: str = Field(..., description="Granular machine-readable error code")
    message: str = Field(..., description="Human-readable explanation of the violation")


class ApiErrorHttpResponse(BaseModel):
    """Standardized RFC 7807 problem details error envelope."""

    code: str = Field(
        ...,
        description="Machine-readable error code, e.g. CONNECTOR_NOT_FOUND, DUPLICATE_FINGERPRINT",
    )
    message: str = Field(..., description="Human-readable summary of the failure")
    detail: str = Field(..., description="Detailed explanation or compatibility alias")
    remediation: str | None = Field(None, description="Actionable guidance for resolving the error")
    disposition: str | None = Field(
        None, description="Operational disposition (FAIL, RETRY, IGNORE)"
    )
    details: list[ErrorDetailHttpResponse] = Field(
        default_factory=list, description="Granular field-specific issues"
    )
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of occurrence")
    trace_id: str | None = Field(
        None, description="Distributed correlation ID for log observability"
    )


def to_error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetailHttpResponse] | None = None,
    trace_id: str | None = None,
    remediation: str | None = None,
    disposition: str | None = None,
) -> JSONResponse:
    """Constructs a standardized JSONResponse from an ApiErrorHttpResponse model."""
    payload = ApiErrorHttpResponse(
        code=code,
        message=message,
        detail=message,
        remediation=remediation,
        disposition=disposition,
        details=details or [],
        timestamp=datetime.now(UTC).isoformat(),
        trace_id=trace_id,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def from_ip_error(
    error: IpError,
    *,
    status_code_override: int | None = None,
    trace_id: str | None = None,
) -> JSONResponse:
    """Translates a first-class IpError value object into a standardized RFC 7807 JSONResponse."""
    return to_error_response(
        status_code=status_code_override or error.http_status,
        code=error.code.value,
        message=error.message,
        remediation=error.remediation,
        disposition=error.disposition.value,
        trace_id=trace_id,
    )
