"""Pure domain error codes and value objects for the Identity bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict


class IdentityErrorCode(StrEnum):
    """Canonical error codes for Identity domain invariant violations."""

    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_TOKEN_NAME = "INVALID_TOKEN_NAME"  # noqa: S105 - Domain error code enum constant, not a secret credential
    INVALID_TOKEN_EXPIRATION = "INVALID_TOKEN_EXPIRATION"  # noqa: S105 - Domain error code enum constant, not a secret credential
    TOKEN_NOT_FOUND = "TOKEN_NOT_FOUND"  # noqa: S105 - Domain error code enum constant, not a secret credential
    TOKEN_ALREADY_REVOKED = "TOKEN_ALREADY_REVOKED"  # noqa: S105 - Domain error code enum constant, not a secret credential
    TOKEN_INACTIVE = "TOKEN_INACTIVE"  # noqa: S105 - Domain error code enum constant, not a secret credential
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105 - Domain error code enum constant, not a secret credential
    IDP_MAPPING_CONFLICT = "IDP_MAPPING_CONFLICT"
    INVALID_USER_STATUS_ACTION = "INVALID_USER_STATUS_ACTION"
    USER_ALREADY_DELETED = "USER_ALREADY_DELETED"


@dataclass(frozen=True, kw_only=True)
class IdentityError:
    """Pure domain error value object for Identity aggregate transitions."""

    code: IdentityErrorCode
    message: str
    details: JsonDict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TokenNotFoundError(IdentityError):
    """Returned when a requested API token does not exist for the tenant."""

    token_id: str = ""
    code: IdentityErrorCode = IdentityErrorCode.TOKEN_NOT_FOUND

    @classmethod
    def for_id(cls, token_id: str) -> TokenNotFoundError:
        return cls(
            token_id=token_id,
            message="Token not found",
            details={"token_id": token_id},
        )


__all__ = [
    "IdentityError",
    "IdentityErrorCode",
    "Result",
    "TokenNotFoundError",
]
