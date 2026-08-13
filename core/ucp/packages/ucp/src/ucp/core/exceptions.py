class DomainError(Exception):
    """Base exception for domain errors."""


class ResourceNotFoundError(DomainError):
    """Raised when a requested resource is not found."""


class IdempotencyConflictError(DomainError):
    """Raised when an idempotency key is reused with a different payload."""


class TenantRenameError(DomainError):
    """Raised when a rename operation violates domain invariants."""


class AppSubscriptionError(DomainError):
    """Raised when a subscription/unsubscription operation violates domain invariants."""


class InfrastructureError(Exception):
    """Base exception for infrastructure and adapter errors."""


class IdentityProviderError(InfrastructureError):
    """Raised when the external Identity Provider fails."""

    def __init__(self, message: str, original_error: str = None, status_code: int = None):  # type: ignore
        super().__init__(message)
        self.original_error = original_error
        self.status_code = status_code
