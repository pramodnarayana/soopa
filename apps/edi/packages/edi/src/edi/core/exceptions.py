class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different payload."""


class OrchestrationError(Exception):
    """Raised when orchestrating an action (like vault creation) fails."""


class VaultError(Exception):
    """Raised when vault operations fail."""


class ResourceNotFoundError(Exception):
    """Raised when a resource is not found."""
