from enum import StrEnum

from seedwork.domain.types import JsonDict


class ErrorCode(StrEnum):
    """Base error codes shared across the platform."""

    # General / System
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"

    # Network / Delivery
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    SSL_ERROR = "SSL_ERROR"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    UNRESOLVABLE_HOST = "UNRESOLVABLE_HOST"
    UNKNOWN_TRANSPORT_ERROR = "UNKNOWN_TRANSPORT_ERROR"

    # Payload / Transformation
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    MISSING_ROUTING_INFO = "MISSING_ROUTING_INFO"
    TRANSFORMATION_FAILED = "TRANSFORMATION_FAILED"


class DomainError(Exception):
    """
    Base class for all core domain exceptions.
    Forces structural compliance for global observability and RFC 7807 API serialization.
    """

    def __init__(
        self,
        message: str,
        code: ErrorCode | str = ErrorCode.INTERNAL_ERROR,
        details: JsonDict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class TransientDomainError(DomainError):
    """
    Raised when a domain operation fails due to a temporary condition (e.g., downstream timeout).
    In a message-driven system, these errors instruct the platform to NACK the message for retry.
    """


class TerminalDomainError(DomainError):
    """
    Raised when a domain operation fails deterministically (e.g., validation failure).
    In a message-driven system, these errors instruct the platform to move the message to a DLQ.
    """
