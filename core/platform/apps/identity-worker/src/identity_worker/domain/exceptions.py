class IdentityProviderPortError(Exception):
    def __init__(
        self, message: str, status_code: int = 500, original_error: Exception | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.original_error = original_error


class IdentityProviderConflictError(IdentityProviderPortError):
    """Raised when the IDP returns a 409 Conflict."""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message, status_code=409, original_error=original_error)


class IdentityProviderNotFoundError(IdentityProviderPortError):
    """Raised when the IDP returns a 404 Not Found."""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message, status_code=404, original_error=original_error)


class IdentityProviderBadRequestError(IdentityProviderPortError):
    """Raised when the IDP returns a 400 Bad Request."""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message, status_code=400, original_error=original_error)
