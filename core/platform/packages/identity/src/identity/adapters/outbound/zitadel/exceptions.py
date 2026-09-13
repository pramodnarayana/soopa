from enum import IntEnum


class HttpStatusCode(IntEnum):
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    CONFLICT = 409
    TOO_MANY_REQUESTS = 429
    INTERNAL_SERVER_ERROR = 500


class ZitadelHttpError(Exception):
    """Base exception for all raw Zitadel HTTP failures."""

    def __init__(self, message: str, status_code: int, original_error: Exception | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.original_error = original_error


class ZitadelHttpConflictError(ZitadelHttpError):
    """Raised when Zitadel returns a 409 Conflict."""


class ZitadelHttpNotFoundError(ZitadelHttpError):
    """Raised when Zitadel returns a 404 Not Found."""


class ZitadelHttpBadRequestError(ZitadelHttpError):
    """Raised when Zitadel returns a 400 Bad Request."""
