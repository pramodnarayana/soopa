class DomainError(Exception):
    """Base exception for domain errors."""


class ResourceNotFoundError(DomainError):
    """Raised when a requested resource is not found."""


class InvalidCapabilityError(DomainError):
    """Raised when an invalid or unknown capability is requested."""


class IdempotencyConflictError(DomainError):
    """Raised when an idempotency key is reused with a different payload."""


class TenantRenameError(DomainError):
    """Raised when a rename operation violates domain invariants."""


class AppSubscriptionError(DomainError):
    """Raised when a subscription/unsubscription operation violates domain invariants."""


class InvalidTenantNameError(DomainError):
    """Raised when a tenant name cannot produce a valid URL-safe slug."""


class SlugExhaustedException(DomainError):
    """Raised when no unique slug variant could be allocated for a tenant name.

    This should be extremely rare in practice (requires MAX_SLUG_ATTEMPTS concurrent
    tenants with identical names). It is a domain error, not an infrastructure error.
    """


class InfrastructureError(Exception):
    """Base exception for infrastructure and adapter errors."""


class IdentityProviderError(InfrastructureError):
    """Raised when the external Identity Provider fails."""

    def __init__(self, message: str, original_error: str = None, status_code: int = None):  # type: ignore
        super().__init__(message)
        self.original_error = original_error
        self.status_code = status_code


class DuplicateEntityError(InfrastructureError):
    """Raised when an infrastructure constraint (e.g. unique constraint) is violated."""

    def __init__(self, message: str, constraint_name: str | None = None):
        super().__init__(message)
        self.constraint_name = constraint_name
