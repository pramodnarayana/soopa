"""Anti-Corruption Layer translator from Identity domain errors to UCP domain errors."""

from __future__ import annotations

from identity.domain.exceptions import IdentityError, IdentityErrorCode

from ucp.domain.exceptions import (
    TokenNotFoundUcpError,
    TokenStateConflictError,
    UcpError,
    UcpValidationError,
    UserStateConflictError,
)


def translate_identity_error(error: IdentityError) -> UcpError:
    """Translates an Identity bounded-context error into a UCP error value object."""
    if error.code in (
        IdentityErrorCode.VALIDATION_FAILED,
        IdentityErrorCode.INVALID_TOKEN_NAME,
        IdentityErrorCode.INVALID_TOKEN_EXPIRATION,
        IdentityErrorCode.INVALID_USER_STATUS_ACTION,
    ):
        return UcpValidationError(message=error.message, details=dict(error.details))
    if error.code == IdentityErrorCode.TOKEN_NOT_FOUND:
        return TokenNotFoundUcpError(message=error.message, details=dict(error.details))
    if error.code in (
        IdentityErrorCode.TOKEN_ALREADY_REVOKED,
        IdentityErrorCode.TOKEN_INACTIVE,
        IdentityErrorCode.TOKEN_EXPIRED,
    ):
        return TokenStateConflictError(message=error.message, details=dict(error.details))
    return UserStateConflictError(message=error.message, details=dict(error.details))
