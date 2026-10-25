from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from seedwork.domain.types import JsonDict

T = TypeVar("T")
E = TypeVar("E")
T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)


@dataclass(frozen=True)
class Result(Generic[T_co, E_co]):
    """Generic, immutable Result monad for First-Class Error Handling without exceptions."""

    value: T_co | None = None
    error: E_co | None = None

    @property
    def is_ok(self) -> bool:
        return self.error is None

    @property
    def is_err(self) -> bool:
        return self.error is not None

    def unwrap(self) -> T_co:
        if self.error is not None or self.value is None:
            raise ValueError(f"Called unwrap on an Err Result: {self.error}")
        return self.value

    def unwrap_err(self) -> E_co:
        if self.error is None:
            raise ValueError("Called unwrap_err on an Ok Result")
        return self.error

    @staticmethod
    def ok(value: T) -> "Result[T, E]":
        return Result(value=value, error=None)

    @staticmethod
    def fail(error: E) -> "Result[T, E]":
        return Result(value=None, error=error)

    @staticmethod
    def err(error: E) -> "Result[T, E]":
        return Result(value=None, error=error)


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
