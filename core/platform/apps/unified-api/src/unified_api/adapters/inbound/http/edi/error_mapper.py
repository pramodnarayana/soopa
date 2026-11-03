"""HTTP boundary error mapper for EDI first-class domain/application errors."""

from __future__ import annotations

from typing import NoReturn

from edi.domain.exceptions import EdiError, EdiErrorCode
from fastapi import HTTPException, status

_NOT_FOUND_CODES: frozenset[EdiErrorCode] = frozenset(
    {
        EdiErrorCode.ROUTE_NOT_FOUND,
        EdiErrorCode.HEADER_NOT_FOUND,
        EdiErrorCode.PARTNER_NOT_FOUND,
        EdiErrorCode.PARTNERSHIP_NOT_FOUND,
        EdiErrorCode.TRACE_NOT_FOUND,
    }
)


def raise_http_for_edi_error(error: EdiError, *, not_found_status: int | None = None) -> NoReturn:
    """Translates a typed `EdiError` value object into a FastAPI `HTTPException`."""
    if error.code in _NOT_FOUND_CODES:
        status_code = (
            not_found_status if not_found_status is not None else status.HTTP_404_NOT_FOUND
        )
    elif error.code == EdiErrorCode.INTERNAL_ERROR:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    else:
        status_code = status.HTTP_400_BAD_REQUEST

    raise HTTPException(status_code=status_code, detail=error.message)
