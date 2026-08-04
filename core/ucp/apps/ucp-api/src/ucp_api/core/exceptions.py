class DomainError(Exception):
    """Base exception for domain errors."""

    pass


class ResourceNotFoundError(DomainError):
    """Raised when a requested resource is not found."""

    pass


class IdempotencyConflictError(DomainError):
    """Raised when an idempotency key is reused with a different payload."""

    pass


class TenantRenameError(DomainError):
    """Raised when a rename operation violates domain invariants."""

    pass


class AppSubscriptionError(DomainError):
    """Raised when a subscription/unsubscription operation violates domain invariants."""

    pass


class InfrastructureError(Exception):
    """Base exception for infrastructure and adapter errors."""

    pass


class IdentityProviderError(InfrastructureError):
    """Raised when the external Identity Provider fails."""

    def __init__(self, message: str, original_error: str = None):  # type: ignore
        super().__init__(message)
        self.original_error = original_error
