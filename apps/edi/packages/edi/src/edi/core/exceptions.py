class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different payload."""


class OrchestrationError(Exception):
    """Raised when orchestrating an action (like vault creation) fails."""


class VaultError(Exception):
    """Raised when vault operations fail."""


class ResourceNotFoundError(Exception):
    """Raised when a resource is not found."""


# --- Domain Errors ---


class DomainError(Exception):
    """Base class for domain-specific errors."""


class PartnerNotFoundError(DomainError):
    """Raised when an AS2 Trading Partner is not found."""

    def __init__(self, partner_id: str, tenant_id: str):
        super().__init__(f"AS2 Partner '{partner_id}' not found for tenant '{tenant_id}'.")
        self.partner_id = partner_id
        self.tenant_id = tenant_id


class InvalidCertificateActionError(DomainError):
    """Raised when an invalid certificate rotation action is provided."""

    def __init__(self, action: str):
        super().__init__(f"Invalid action '{action}'. Must be 'generate' or 'upload'.")
        self.action = action


class MissingCertificateError(DomainError):
    """Raised when required certificates are missing."""

    def __init__(self, message: str):
        super().__init__(message)


class TransactionNotFoundError(DomainError):
    """Raised when an EDI Transaction trace is not found."""

    def __init__(self, trace_id: str):
        super().__init__(f"Transaction trace '{trace_id}' not found.")
        self.trace_id = trace_id
