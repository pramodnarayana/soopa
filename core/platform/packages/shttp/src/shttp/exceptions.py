"""Typed platform exceptions for HTTP client operations and security."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Self, TypeVar

import httpx

TError = TypeVar("TError", bound="HttpStatusError")
_STATUS_CODE_REGISTRY: dict[int, type[HttpStatusError]] = {}


def register_status_error(*status_codes: int) -> Callable[[type[TError]], type[TError]]:
    """Decorator registering an HttpStatusError subclass for specific HTTP status codes."""

    def decorator(cls: type[TError]) -> type[TError]:
        for code in status_codes:
            _STATUS_CODE_REGISTRY[code] = cls
        return cls

    return decorator


class SsrfViolationReason(StrEnum):
    """Reason why an outbound target URL violated SSRF security policy."""

    INVALID_SCHEME = "INVALID_SCHEME"
    MISSING_HOSTNAME = "MISSING_HOSTNAME"
    UNRESOLVABLE_HOST = "UNRESOLVABLE_HOST"
    RESTRICTED_IP = "RESTRICTED_IP"


class TimeoutKind(StrEnum):
    """Kind of network timeout encountered."""

    CONNECT = "CONNECT"
    READ = "READ"
    WRITE = "WRITE"
    POOL = "POOL"


class FailureDisposition(StrEnum):
    """Actionable engine disposition indicating how upstream workflows should handle this failure."""

    RETRY = "RETRY"  # Transient fault: retry with backoff or NACK message
    FAIL = "FAIL"  # Terminal/configuration fault: stop, dead-letter, alert user
    IGNORE = "IGNORE"  # Benign fault: log and skip without aborting


class HttpFailureClassification(StrEnum):
    """Normalized domain-friendly classification of HTTP operational failures."""

    AUTH_FAILURE = "AUTH_FAILURE"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CONFLICT = "CONFLICT"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    UNCLASSIFIED = "UNCLASSIFIED"


class HttpError(Exception):
    """Base class for all platform HTTP exceptions with failure classification and user remediation."""

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.url = url
        self._remediation = remediation
        self._disposition = disposition
        self.details = details or {}

    def classify(self) -> HttpFailureClassification:
        """Returns the high-level operational classification of this failure."""
        return HttpFailureClassification.UNCLASSIFIED

    @property
    def disposition(self) -> FailureDisposition:
        """Actionable engine disposition (RETRY, FAIL, or IGNORE)."""
        if self._disposition is not None:
            return self._disposition
        classification = self.classify()
        if classification in (
            HttpFailureClassification.TIMEOUT,
            HttpFailureClassification.NETWORK_UNAVAILABLE,
            HttpFailureClassification.RATE_LIMIT_EXCEEDED,
            HttpFailureClassification.SERVER_ERROR,
        ):
            return FailureDisposition.RETRY
        return FailureDisposition.FAIL

    @property
    def remediation(self) -> str | None:
        """Human-readable remediation guidance instructing how to resolve this failure."""
        return self._remediation


class SsrfSecurityError(HttpError, ValueError):
    """Raised when an outbound URL violates SSRF security boundaries or DNS resolution fails."""

    DEFAULT_REMEDIATION = (
        "Destination URL resolves to a restricted private, link-local, or loopback network IP address. "
        "Ensure public internet endpoints are specified in your connector configuration."
    )

    def __init__(
        self,
        message: str,
        *,
        url: str,
        reason: SsrfViolationReason,
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(
            message,
            url=url,
            remediation=remediation or self.DEFAULT_REMEDIATION,
            disposition=disposition or FailureDisposition.FAIL,
        )
        self.reason = reason
        self.cause = cause

    def classify(self) -> HttpFailureClassification:
        return HttpFailureClassification.SECURITY_VIOLATION


class HttpNetworkError(HttpError):
    """Raised when a socket or underlying network connection fails."""

    DEFAULT_REMEDIATION = (
        "Underlying network socket connection failed. Verify destination host DNS resolution, "
        "firewall egress rules, and that the remote server is accepting connections."
    )

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        cause: BaseException | None = None,
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
    ) -> None:
        super().__init__(
            message,
            url=url,
            remediation=remediation or self.DEFAULT_REMEDIATION,
            disposition=disposition or FailureDisposition.RETRY,
        )
        self.cause = cause

    def classify(self) -> HttpFailureClassification:
        return HttpFailureClassification.NETWORK_UNAVAILABLE


class HttpTimeoutError(HttpNetworkError):
    """Raised when an HTTP operation exceeds configured connect, read, or pool timeouts."""

    DEFAULT_REMEDIATION = (
        "Network connection or read timed out communicating with upstream host. "
        "Verify upstream host responsiveness and check if connection limits should be increased."
    )

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        kind: TimeoutKind = TimeoutKind.READ,
        cause: BaseException | None = None,
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
    ) -> None:
        super().__init__(
            message,
            url=url,
            cause=cause,
            remediation=remediation or self.DEFAULT_REMEDIATION,
            disposition=disposition or FailureDisposition.RETRY,
        )
        self.kind = kind

    def classify(self) -> HttpFailureClassification:
        return HttpFailureClassification.TIMEOUT


class HttpStatusError(HttpError):
    """Raised when an HTTP response indicates an unexpected client or server error (4xx/5xx)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        url: str,
        response_text: str = "",
        headers: Mapping[str, str] | None = None,
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
    ) -> None:
        super().__init__(message, url=url, remediation=remediation, disposition=disposition)
        self.status_code = status_code
        self.response_text = response_text
        self.headers = headers or {}

    @classmethod
    def from_response(cls, response: httpx.Response) -> Self:
        """Constructs this exception from an HTTP response."""
        url = str(response.url)
        try:
            response_text = response.text[:2048]
        except (RuntimeError, ValueError):
            response_text = ""
        message = f"HTTP {response.status_code} error from '{url}': {response_text}"
        return cls(
            message,
            status_code=response.status_code,
            url=url,
            response_text=response_text,
            headers=response.headers,
        )

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        return 500 <= self.status_code < 600

    def classify(self) -> HttpFailureClassification:
        if self.is_server_error:
            return HttpFailureClassification.SERVER_ERROR
        return HttpFailureClassification.UNCLASSIFIED


@register_status_error(401, 403)
class HttpAuthError(HttpStatusError):
    """Raised when the remote server returns 401 Unauthorized or 403 Forbidden."""

    DEFAULT_REMEDIATION = (
        "Authentication failed (401/403). Verify that your API keys, OAuth tokens, "
        "or partner certificate credentials are valid and have not expired in connector settings."
    )

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        url: str,
        response_text: str = "",
        headers: Mapping[str, str] | None = None,
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            url=url,
            response_text=response_text,
            headers=headers,
            remediation=remediation or self.DEFAULT_REMEDIATION,
            disposition=disposition or FailureDisposition.FAIL,
        )

    def classify(self) -> HttpFailureClassification:
        return HttpFailureClassification.AUTH_FAILURE


@register_status_error(404)
class HttpNotFoundError(HttpStatusError):
    """Raised when the remote server returns 404 Not Found."""

    DEFAULT_REMEDIATION = (
        "The requested endpoint or resource was not found (404). Verify the API endpoint path, "
        "resource identifier, and versioning configuration."
    )

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 404,
        url: str,
        response_text: str = "",
        headers: Mapping[str, str] | None = None,
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            url=url,
            response_text=response_text,
            headers=headers,
            remediation=remediation or self.DEFAULT_REMEDIATION,
            disposition=disposition or FailureDisposition.FAIL,
        )

    def classify(self) -> HttpFailureClassification:
        return HttpFailureClassification.RESOURCE_NOT_FOUND


@register_status_error(429)
class HttpRateLimitError(HttpStatusError):
    """Raised when the remote server returns 429 Too Many Requests."""

    DEFAULT_REMEDIATION = (
        "API rate limit exceeded (429). The system will automatically backoff and "
        "retry after the cooldown window specified in the upstream server headers."
    )

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 429,
        url: str,
        response_text: str = "",
        headers: Mapping[str, str] | None = None,
        retry_after_seconds: float | None = None,
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            url=url,
            response_text=response_text,
            headers=headers,
            remediation=remediation or self.DEFAULT_REMEDIATION,
            disposition=disposition or FailureDisposition.RETRY,
        )
        self.retry_after_seconds = retry_after_seconds

    @classmethod
    def from_response(cls, response: httpx.Response) -> Self:
        url = str(response.url)
        try:
            response_text = response.text[:2048]
        except (RuntimeError, ValueError):
            response_text = ""
        retry_after_raw = response.headers.get("retry-after") or response.headers.get("Retry-After")
        retry_seconds: float | None = None
        if retry_after_raw and retry_after_raw.isdigit():
            retry_seconds = float(retry_after_raw)
        message = f"HTTP 429 Too Many Requests from '{url}': {response_text}"
        return cls(
            message,
            status_code=429,
            url=url,
            response_text=response_text,
            headers=response.headers,
            retry_after_seconds=retry_seconds,
        )

    def classify(self) -> HttpFailureClassification:
        return HttpFailureClassification.RATE_LIMIT_EXCEEDED


@register_status_error(500, 502, 503, 504)
class HttpServerError(HttpStatusError):
    """Raised when the remote server returns a 5xx server error."""

    DEFAULT_REMEDIATION = (
        "Upstream remote server returned an internal server error (5xx). The fault is on the "
        "remote service provider's end and will be retried automatically with exponential backoff."
    )

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        url: str,
        response_text: str = "",
        headers: Mapping[str, str] | None = None,
        remediation: str | None = None,
        disposition: FailureDisposition | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            url=url,
            response_text=response_text,
            headers=headers,
            remediation=remediation or self.DEFAULT_REMEDIATION,
            disposition=disposition or FailureDisposition.RETRY,
        )

    def classify(self) -> HttpFailureClassification:
        return HttpFailureClassification.SERVER_ERROR


class HttpRetriesExhaustedError(HttpError):
    """Raised when resilient retry attempts have been exhausted for transient faults."""

    def __init__(
        self,
        message: str,
        *,
        url: str,
        attempts: int,
        last_response: httpx.Response | None = None,
        last_error: BaseException | None = None,
    ) -> None:
        super().__init__(message, url=url)
        self.attempts = attempts
        self.last_response = last_response
        self.last_error = last_error

    def classify(self) -> HttpFailureClassification:
        if self.last_response is not None:
            if self.last_response.status_code == 429:
                return HttpFailureClassification.RATE_LIMIT_EXCEEDED
            if self.last_response.status_code >= 500:
                return HttpFailureClassification.SERVER_ERROR
        if isinstance(self.last_error, HttpTimeoutError):
            return HttpFailureClassification.TIMEOUT
        return HttpFailureClassification.NETWORK_UNAVAILABLE


def classify_http_failure(target: Exception | httpx.Response) -> HttpFailureClassification:
    """Classifies an HTTP exception or response into a normalized domain-friendly failure category."""
    if isinstance(target, HttpError):
        return target.classify()
    if isinstance(target, httpx.Response):
        if target.status_code in (401, 403):
            return HttpFailureClassification.AUTH_FAILURE
        if target.status_code == 404:
            return HttpFailureClassification.RESOURCE_NOT_FOUND
        if target.status_code == 429:
            return HttpFailureClassification.RATE_LIMIT_EXCEEDED
        if target.status_code >= 500:
            return HttpFailureClassification.SERVER_ERROR
    return HttpFailureClassification.UNCLASSIFIED
