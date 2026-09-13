class IdentityProviderPortError(Exception):
    def __init__(
        self, message: str, status_code: int = 500, original_error: Exception | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.original_error = original_error


class IdentityProviderConflictError(IdentityProviderPortError):
    """Raised when the IDP returns a 409 Conflict."""


class IdentityProviderNotFoundError(IdentityProviderPortError):
    """Raised when the IDP returns a 404 Not Found."""


class IdentityProviderBadRequestError(IdentityProviderPortError):
    """Raised when the IDP returns a 400 Bad Request."""
