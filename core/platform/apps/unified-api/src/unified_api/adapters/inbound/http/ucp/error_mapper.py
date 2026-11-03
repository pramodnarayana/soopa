"""HTTP boundary error mapper for UCP first-class domain/application errors."""

from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException, status
from ucp.domain.exceptions import UcpError, UcpErrorCode

_NOT_FOUND_CODES: frozenset[UcpErrorCode] = frozenset(
    {
        UcpErrorCode.TENANT_NOT_FOUND,
        UcpErrorCode.APP_NOT_FOUND,
        UcpErrorCode.USER_NOT_FOUND,
        UcpErrorCode.ROLE_NOT_FOUND,
        UcpErrorCode.WEBHOOK_NOT_FOUND,
        UcpErrorCode.TOKEN_NOT_FOUND,
    }
)

_CONFLICT_CODES: frozenset[UcpErrorCode] = frozenset(
    {
        UcpErrorCode.IDP_ORGANIZATION_CONFLICT,
        UcpErrorCode.MISSING_IDP_ORGANIZATION,
        UcpErrorCode.TENANT_ALREADY_DELETED,
        UcpErrorCode.WEBHOOK_ALREADY_DELETED,
        UcpErrorCode.SLUG_EXHAUSTED,
        UcpErrorCode.TOKEN_STATE_CONFLICT,
        UcpErrorCode.USER_STATE_CONFLICT,
    }
)


def raise_http_for_ucp_error(error: UcpError, *, not_found_status: int | None = None) -> NoReturn:
    """Translates a typed `UcpError` value object into a FastAPI `HTTPException`."""
    if error.code in _NOT_FOUND_CODES:
        status_code = (
            not_found_status if not_found_status is not None else status.HTTP_404_NOT_FOUND
        )
    elif error.code in _CONFLICT_CODES:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_400_BAD_REQUEST

    raise HTTPException(status_code=status_code, detail=error.message)
