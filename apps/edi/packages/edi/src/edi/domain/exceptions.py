"""Domain Exceptions and First-Class Domain Error Value Objects for EDI.

Adheres strictly to the Enterprise First-Class Error Handling standard:
- Known domain and operational errors are modeled as immutable Value Objects
  (`EdiError` subclasses) returned via `Result[T, EdiError]`.
- Exceptions are reserved for exceptional runtime failures and infrastructural halts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from seedwork.domain.exceptions import DomainError as SeedworkDomainError
from seedwork.domain.exceptions import ErrorCode, Result
from seedwork.domain.types import JsonDict

# --- First-Class Domain Error Codes & Value Objects ---


class EdiErrorCode(StrEnum):
    """Enumeration of domain error codes across EDI bounded subdomains."""

    # Routing & Header Invariants
    INVALID_DESTINATION_MUTUAL_EXCLUSIVITY = "INVALID_DESTINATION_MUTUAL_EXCLUSIVITY"
    ROUTE_ALREADY_ACTIVE = "ROUTE_ALREADY_ACTIVE"
    ROUTE_ALREADY_INACTIVE = "ROUTE_ALREADY_INACTIVE"
    INVALID_MATCHING_CRITERIA = "INVALID_MATCHING_CRITERIA"
    ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
    HEADER_NOT_FOUND = "HEADER_NOT_FOUND"

    # Partner & Partnership Invariants
    PARTNER_NOT_FOUND = "PARTNER_NOT_FOUND"
    PARTNER_ALREADY_EXISTS = "PARTNER_ALREADY_EXISTS"
    PARTNER_IN_USE = "PARTNER_IN_USE"
    PARTNERSHIP_NOT_FOUND = "PARTNERSHIP_NOT_FOUND"
    INVALID_CERTIFICATE_ACTION = "INVALID_CERTIFICATE_ACTION"
    MISSING_CERTIFICATE = "MISSING_CERTIFICATE"
    PARTNER_ALREADY_ACTIVE = "PARTNER_ALREADY_ACTIVE"
    PARTNER_ALREADY_INACTIVE = "PARTNER_ALREADY_INACTIVE"

    # Trace / Processing Invariants
    TRACE_NOT_FOUND = "TRACE_NOT_FOUND"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, kw_only=True)
class EdiError:
    """Base immutable value object for known EDI domain and operational errors (NOT an Exception)."""

    code: EdiErrorCode
    message: str
    details: JsonDict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class EdiValidationError(EdiError):
    """Generic EDI validation failure value object."""

    code: EdiErrorCode = EdiErrorCode.VALIDATION_FAILED

    @classmethod
    def with_message(cls, message: str, details: JsonDict | None = None) -> EdiValidationError:
        return cls(message=message, details=details or {})


@dataclass(frozen=True, kw_only=True)
class EdiRoutingError(EdiError):
    """Domain errors specific to EDI Inbound Route, Outbound Route, and Header aggregates."""


@dataclass(frozen=True, kw_only=True)
class RouteNotFoundEdiError(EdiRoutingError):
    """Returned when an inbound or outbound route does not exist."""

    code: EdiErrorCode = EdiErrorCode.ROUTE_NOT_FOUND

    @classmethod
    def for_id(cls, route_id: str, *, direction: str = "INBOUND") -> RouteNotFoundEdiError:
        label = "Inbound route" if direction.upper() == "INBOUND" else "Outbound route"
        return cls(
            message=f"{label} '{route_id}' not found.",
            details={"route_id": route_id, "direction": direction},
        )


@dataclass(frozen=True, kw_only=True)
class HeaderNotFoundEdiError(EdiRoutingError):
    """Returned when an outbound EDI header does not exist."""

    code: EdiErrorCode = EdiErrorCode.HEADER_NOT_FOUND

    @classmethod
    def for_id(cls, header_id: str, tenant_id: str) -> HeaderNotFoundEdiError:
        return cls(
            message=f"Outbound EDI header '{header_id}' not found.",
            details={"header_id": header_id, "tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class EdiPartnerError(EdiError):
    """Domain errors specific to EDI AS2 and SFTP Trading Partner aggregates."""


@dataclass(frozen=True, kw_only=True)
class PartnerNotFoundEdiError(EdiPartnerError):
    """Returned when an AS2 or SFTP Trading Partner does not exist."""

    code: EdiErrorCode = EdiErrorCode.PARTNER_NOT_FOUND

    @classmethod
    def for_id(
        cls,
        partner_id: str,
        tenant_id: str,
        *,
        protocol: str = "AS2",
    ) -> PartnerNotFoundEdiError:
        return cls(
            message=f"{protocol} Partner '{partner_id}' not found for tenant '{tenant_id}'.",
            details={"partner_id": partner_id, "tenant_id": tenant_id, "protocol": protocol},
        )


@dataclass(frozen=True, kw_only=True)
class PartnerAlreadyExistsEdiError(EdiPartnerError):
    """Returned when an AS2 Trading Partner with the same AS2 ID already exists."""

    code: EdiErrorCode = EdiErrorCode.PARTNER_ALREADY_EXISTS

    @classmethod
    def for_as2_id(cls, as2_id: str, tenant_id: str) -> PartnerAlreadyExistsEdiError:
        return cls(
            message=f"AS2 Partner with AS2 ID '{as2_id}' already exists for tenant '{tenant_id}'.",
            details={"as2_id": as2_id, "tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class PartnerInUseEdiError(EdiPartnerError):
    """Returned when a Trading Partner cannot be deleted because it is referenced by active routes or partnerships."""

    code: EdiErrorCode = EdiErrorCode.PARTNER_IN_USE

    @classmethod
    def for_id(cls, partner_id: str, tenant_id: str) -> PartnerInUseEdiError:
        return cls(
            message=(
                f"AS2 Partner '{partner_id}' for tenant '{tenant_id}' is in use "
                "and cannot be deleted."
            ),
            details={"partner_id": partner_id, "tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class PartnershipNotFoundEdiError(EdiPartnerError):
    """Returned when an AS2 Partnership does not exist."""

    code: EdiErrorCode = EdiErrorCode.PARTNERSHIP_NOT_FOUND

    @classmethod
    def for_id(cls, partnership_id: str, tenant_id: str) -> PartnershipNotFoundEdiError:
        return cls(
            message=f"AS2 partnership '{partnership_id}' not found.",
            details={"partnership_id": partnership_id, "tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class InvalidCertificateActionEdiError(EdiPartnerError):
    """Returned when an unsupported certificate rotation action is requested."""

    code: EdiErrorCode = EdiErrorCode.INVALID_CERTIFICATE_ACTION

    @classmethod
    def for_action(cls, action: str) -> InvalidCertificateActionEdiError:
        return cls(
            message=f"Invalid action '{action}'. Must be 'generate' or 'upload'.",
            details={"action": action},
        )


@dataclass(frozen=True, kw_only=True)
class MissingCertificateEdiError(EdiPartnerError):
    """Returned when required S/MIME certificate or key material is absent."""

    code: EdiErrorCode = EdiErrorCode.MISSING_CERTIFICATE

    @classmethod
    def with_message(cls, message: str) -> MissingCertificateEdiError:
        return cls(message=message)


@dataclass(frozen=True, kw_only=True)
class TraceNotFoundEdiError(EdiError):
    """Returned when an EDI pipeline execution trace cannot be found."""

    code: EdiErrorCode = EdiErrorCode.TRACE_NOT_FOUND

    @classmethod
    def for_trace_id(cls, trace_id: str) -> TraceNotFoundEdiError:
        return cls(
            message=f"EDI trace '{trace_id}' not found.",
            details={"trace_id": trace_id},
        )


@dataclass(frozen=True, kw_only=True)
class InvalidPayloadEdiError(EdiError):
    """Returned when an EDI payload or replay request is structurally invalid."""

    code: EdiErrorCode = EdiErrorCode.INVALID_PAYLOAD

    @classmethod
    def with_message(cls, message: str, details: JsonDict | None = None) -> InvalidPayloadEdiError:
        return cls(message=message, details=details or {})


# --- Infrastructural & Pipeline Exceptions ---


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key is reused with a different payload."""


class OrchestrationError(Exception):
    """Raised when orchestrating an external infrastructure action (like vault creation) fails."""


class VaultError(Exception):
    """Raised when vault operations fail."""


class ResourceNotFoundError(Exception):
    """Raised when an external infrastructure resource is not found."""


class DomainError(SeedworkDomainError):
    """Base class for pipeline/worker exceptions that trigger SQS dead-lettering or retry control."""


class InvalidMessageError(DomainError):
    """Raised when an inbound queue message is permanently malformed or unprocessable.

    Unlike transient infrastructure errors (which should be retried via NACK),
    this exception signals a message that is structurally invalid and should be
    dead-lettered immediately without retry.
    """


class PartnerNotFoundError(DomainError):
    """Raised by repository/worker adapters when an AS2 Trading Partner is not found."""

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
    """Raised by repository adapters when a unique AS2 ID constraint is violated."""

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
    """Raised by repository adapters when a foreign-key constraint blocks partner deletion."""

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


class SftpPartnerAlreadyExistsError(DomainError):
    """Raised by repository adapters when an SFTP partner unique constraint is violated."""

    def __init__(self, name: str, tenant_id: str) -> None:
        self._name = name
        self._tenant_id = tenant_id
        super().__init__(
            message=f"SFTP Partner '{name}' already exists for tenant '{tenant_id}'.",
            code=ErrorCode.CONFLICT,
            details={"name": name, "tenant_id": tenant_id},
        )


class PartnershipAlreadyExistsError(DomainError):
    """Raised by repository adapters when an active AS2 partnership already exists."""

    def __init__(self, tenant_id: str, local_partner_id: str, remote_partner_id: str) -> None:
        super().__init__(
            message=(
                f"An active partnership already exists between '{local_partner_id}' "
                f"and '{remote_partner_id}' for tenant '{tenant_id}'."
            ),
            code=ErrorCode.CONFLICT,
            details={
                "tenant_id": tenant_id,
                "local_partner_id": local_partner_id,
                "remote_partner_id": remote_partner_id,
            },
        )


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
    """Raised when required certificates are missing in worker execution."""


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
    """Raised when an inbound or outbound route cannot be resolved in pipeline execution."""

    def __init__(self, direction: str, sender_id: str, receiver_id: str):
        super().__init__(
            message=f"No route found for {direction} {sender_id}->{receiver_id}",
            code=ErrorCode.NOT_FOUND,
            details={"direction": direction, "sender_id": sender_id, "receiver_id": receiver_id},
        )


class TraceNotFoundError(DomainError):
    """Raised when an EDI pipeline trace is not found in worker execution."""

    def __init__(self, trace_id: str):
        self._trace_id = trace_id
        super().__init__(
            message=f"EDI trace '{trace_id}' not found.",
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
    """Raised when the outbound transform pipeline cannot determine the EDI transaction type."""

    def __init__(self, trace_id: str):
        super().__init__(
            message=f"Cannot determine transaction_type for trace_id='{trace_id}'. "
            "Provide it explicitly in the API request body (transaction_type field) "
            "or configure a concrete transaction_type on the outbound route.",
            code=ErrorCode.VALIDATION_FAILED,
            details={"trace_id": trace_id},
        )


class EdiTransformationError(DomainError):
    """Raised when an EDI payload fails syntax or structural AST transformation."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        self.errors: list[str] = list(errors) if errors else []
        super().__init__(
            message=message,
            code=ErrorCode.TRANSFORMATION_FAILED,
            details={"errors": list(self.errors)} if self.errors else {},
        )


__all__ = [
    "DomainError",
    "EdiError",
    "EdiErrorCode",
    "EdiPartnerError",
    "EdiRoutingError",
    "EdiTransformationError",
    "EdiValidationError",
    "HeaderNotFoundEdiError",
    "IdempotencyConflictError",
    "InvalidCertificateActionEdiError",
    "InvalidCertificateActionError",
    "InvalidMessageError",
    "InvalidMessageFormatError",
    "InvalidPayloadEdiError",
    "MissingCertificateEdiError",
    "MissingCertificateError",
    "MissingRoutingInformationError",
    "OrchestrationError",
    "OutboundRouteNotFoundError",
    "PartnerAlreadyExistsEdiError",
    "PartnerAlreadyExistsError",
    "PartnerInUseEdiError",
    "PartnerInUseError",
    "PartnerNotFoundEdiError",
    "PartnerNotFoundError",
    "PartnershipAlreadyExistsError",
    "PartnershipNotFoundEdiError",
    "ResourceNotFoundError",
    "Result",
    "RouteNotFoundEdiError",
    "RouteNotFoundError",
    "SftpPartnerAlreadyExistsError",
    "TraceNotFoundEdiError",
    "TraceNotFoundError",
    "UnresolvableConnectionTypeError",
    "UnresolvableTransactionTypeError",
    "VaultError",
]
