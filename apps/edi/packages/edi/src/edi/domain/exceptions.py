class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different payload."""


class OrchestrationError(Exception):
    """Raised when orchestrating an action (like vault creation) fails."""


class VaultError(Exception):
    """Raised when vault operations fail."""


class ResourceNotFoundError(Exception):
    """Raised when a resource is not found."""


from seedwork.domain.exceptions import DomainError as SeedworkDomainError
from seedwork.domain.exceptions import ErrorCode

# --- Domain Errors ---


class DomainError(SeedworkDomainError):
    """Base class for domain-specific errors."""


class InvalidMessageError(DomainError):
    """Raised when an inbound queue message is permanently malformed or unprocessable.

    Unlike transient infrastructure errors (which should be retried via NACK),
    this exception signals a message that is structurally invalid and should be
    dead-lettered immediately without retry.
    """


class PartnerNotFoundError(DomainError):
    """Raised when an AS2 Trading Partner is not found."""

    def __init__(self, partner_id: str, tenant_id: str):
        self._partner_id = partner_id
        self._tenant_id = tenant_id
        super().__init__(
            message=f"AS2 Partner '{partner_id}' not found for tenant '{tenant_id}'.",
            code=ErrorCode.NOT_FOUND,
            details={"partner_id": partner_id, "tenant_id": tenant_id},
        )

    @property
    def partner_id(self) -> str:
        return self._partner_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id


class PartnerAlreadyExistsError(DomainError):
    """Raised when an AS2 Trading Partner already exists (e.g. duplicate AS2 ID)."""

    def __init__(self, as2_id: str, tenant_id: str):
        self._as2_id = as2_id
        self._tenant_id = tenant_id
        super().__init__(
            message=f"AS2 Partner with AS2 ID '{as2_id}' already exists for tenant '{tenant_id}'.",
            code=ErrorCode.CONFLICT,
            details={"as2_id": as2_id, "tenant_id": tenant_id},
        )

    @property
    def as2_id(self) -> str:
        return self._as2_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id


class PartnerInUseError(DomainError):
    """Raised when an AS2 Trading Partner cannot be deleted because it is in use."""

    def __init__(self, partner_id: str, tenant_id: str):
        self._partner_id = partner_id
        self._tenant_id = tenant_id
        super().__init__(
            message=f"AS2 Partner '{partner_id}' for tenant '{tenant_id}' is in use and cannot be deleted.",
            code=ErrorCode.CONFLICT,
            details={"partner_id": partner_id, "tenant_id": tenant_id},
        )

    @property
    def partner_id(self) -> str:
        return self._partner_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id


class InvalidCertificateActionError(DomainError):
    """Raised when an invalid certificate rotation action is provided."""

    def __init__(self, action: str):
        self._action = action
        super().__init__(
            message=f"Invalid action '{action}'. Must be 'generate' or 'upload'.",
            code=ErrorCode.VALIDATION_FAILED,
            details={"action": action},
        )

    @property
    def action(self) -> str:
        return self._action


class MissingCertificateError(DomainError):
    """Raised when required certificates are missing."""


class MissingRoutingInformationError(DomainError):
    """Raised when an EDI message is missing sender/receiver IDs for routing."""

    def __init__(self, trace_id: str):
        self._trace_id = trace_id
        super().__init__(
            message=f"EDI Message {trace_id} is missing sender/receiver IDs for routing.",
            code=ErrorCode.MISSING_ROUTING_INFO,
            details={"trace_id": trace_id},
        )

    @property
    def trace_id(self) -> str:
        return self._trace_id


class RouteNotFoundError(DomainError):
    """Raised when an inbound or outbound route cannot be resolved."""

    def __init__(self, direction: str, sender_id: str, receiver_id: str):
        super().__init__(
            message=f"No route found for {direction} {sender_id}->{receiver_id}",
            code=ErrorCode.NOT_FOUND,
            details={"direction": direction, "sender_id": sender_id, "receiver_id": receiver_id},
        )


class TransactionNotFoundError(DomainError):
    """Raised when an EDI Transaction trace is not found."""

    def __init__(self, trace_id: str):
        self._trace_id = trace_id
        super().__init__(
            message=f"Transaction trace '{trace_id}' not found.",
            code=ErrorCode.NOT_FOUND,
            details={"trace_id": trace_id},
        )

    @property
    def trace_id(self) -> str:
        return self._trace_id


class InvalidMessageFormatError(DomainError):
    """Raised when an EDI payload or envelope is structurally invalid or missing required metadata."""

    def __init__(self, message: str):
        super().__init__(message=message, code=ErrorCode.INVALID_PAYLOAD)


class UnresolvableConnectionTypeError(DomainError):
    """Raised when the connection type (e.g., AS2, SFTP) cannot be resolved from the route configuration."""

    def __init__(self, message: str = "Unresolvable connection type from route configuration."):
        super().__init__(message=message, code=ErrorCode.VALIDATION_FAILED)


class OutboundRouteNotFoundError(DomainError):
    """Raised when the outbound EDI header or route config cannot be resolved for a trading partner."""

    def __init__(self, trading_partner_id: str, tenant_id: str):
        super().__init__(
            message=f"No outbound route/header found for trading_partner_id='{trading_partner_id}' and tenant_id='{tenant_id}'.",
            code=ErrorCode.NOT_FOUND,
            details={"trading_partner_id": trading_partner_id, "tenant_id": tenant_id},
        )


class UnresolvableTransactionTypeError(DomainError):
    """
    Raised when the outbound transform pipeline cannot determine the EDI
    transaction type for a given trace.
    """

    def __init__(self, trace_id: str):
        super().__init__(
            message=f"Cannot determine transaction_type for trace_id='{trace_id}'. "
            "Provide it explicitly in the API request body (transaction_type field) "
            "or configure a concrete transaction_type on the outbound route.",
            code=ErrorCode.VALIDATION_FAILED,
            details={"trace_id": trace_id},
        )
