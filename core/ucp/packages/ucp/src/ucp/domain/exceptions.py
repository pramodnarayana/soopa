"""First-class domain and application error value objects for the UCP bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict


class UcpErrorCode(StrEnum):
    """Canonical error codes for all known UCP domain and application outcomes."""

    VALIDATION_FAILED = "VALIDATION_FAILED"
    EMPTY_TENANT_NAME = "EMPTY_TENANT_NAME"
    INVALID_TENANT_NAME = "INVALID_TENANT_NAME"
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"
    TENANT_ALREADY_DELETED = "TENANT_ALREADY_DELETED"
    MISSING_IDP_ORGANIZATION = "MISSING_IDP_ORGANIZATION"
    IDP_ORGANIZATION_CONFLICT = "IDP_ORGANIZATION_CONFLICT"
    SLUG_EXHAUSTED = "SLUG_EXHAUSTED"
    TENANT_INACTIVE_FOR_SUBSCRIPTION = "TENANT_INACTIVE_FOR_SUBSCRIPTION"
    APP_NOT_FOUND = "APP_NOT_FOUND"
    APP_ALREADY_SUBSCRIBED = "APP_ALREADY_SUBSCRIBED"
    APP_NOT_SUBSCRIBED = "APP_NOT_SUBSCRIBED"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_STATE_CONFLICT = "USER_STATE_CONFLICT"
    ROLE_NOT_FOUND = "ROLE_NOT_FOUND"
    INVALID_CAPABILITY = "INVALID_CAPABILITY"
    WEBHOOK_NOT_FOUND = "WEBHOOK_NOT_FOUND"
    WEBHOOK_ALREADY_DELETED = "WEBHOOK_ALREADY_DELETED"
    TOKEN_NOT_FOUND = "TOKEN_NOT_FOUND"  # noqa: S105 - Domain error code enum constant, not a secret credential
    TOKEN_STATE_CONFLICT = "TOKEN_STATE_CONFLICT"  # noqa: S105 - Domain error code enum constant, not a secret credential


@dataclass(frozen=True, kw_only=True)
class UcpError:
    """Base immutable value object for all known UCP domain and operational errors."""

    code: UcpErrorCode
    message: str
    details: JsonDict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class UcpValidationError(UcpError):
    code: UcpErrorCode = UcpErrorCode.VALIDATION_FAILED

    @classmethod
    def with_message(cls, message: str, details: JsonDict | None = None) -> UcpValidationError:
        return cls(message=message, details=details or {})


@dataclass(frozen=True, kw_only=True)
class EmptyTenantNameError(UcpError):
    code: UcpErrorCode = UcpErrorCode.EMPTY_TENANT_NAME
    message: str = "Tenant name cannot be empty."


@dataclass(frozen=True, kw_only=True)
class InvalidTenantSlugError(UcpError):
    code: UcpErrorCode = UcpErrorCode.INVALID_TENANT_NAME

    @classmethod
    def for_name(cls, name: str) -> InvalidTenantSlugError:
        return cls(
            message=(
                f"Tenant name {name!r} produces an empty slug. "
                "Please use at least one alphanumeric character."
            ),
            details={"name": name},
        )


@dataclass(frozen=True, kw_only=True)
class TenantNotFoundError(UcpError):
    tenant_id: str = ""
    code: UcpErrorCode = UcpErrorCode.TENANT_NOT_FOUND

    @classmethod
    def for_id(cls, tenant_id: str) -> TenantNotFoundError:
        return cls(
            tenant_id=tenant_id,
            message=f"Tenant '{tenant_id}' not found.",
            details={"tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class TenantAlreadyDeletedError(UcpError):
    tenant_id: str = ""
    code: UcpErrorCode = UcpErrorCode.TENANT_ALREADY_DELETED

    @classmethod
    def for_id(cls, tenant_id: str) -> TenantAlreadyDeletedError:
        return cls(
            tenant_id=tenant_id,
            message=f"Tenant '{tenant_id}' has already been deleted.",
            details={"tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class MissingIdpOrganizationError(UcpError):
    tenant_id: str = ""
    code: UcpErrorCode = UcpErrorCode.MISSING_IDP_ORGANIZATION

    @classmethod
    def for_tenant(cls, tenant_id: str) -> MissingIdpOrganizationError:
        return cls(
            tenant_id=tenant_id,
            message=f"Tenant {tenant_id} has no associated IDP organization",
            details={"tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class IdpOrganizationConflictError(UcpError):
    idp_tenant_id: str = ""
    code: UcpErrorCode = UcpErrorCode.IDP_ORGANIZATION_CONFLICT

    @classmethod
    def for_org(cls, existing_idp_tenant_id: str) -> IdpOrganizationConflictError:
        return cls(
            idp_tenant_id=existing_idp_tenant_id,
            message=(
                "Tenant already has a different IDP organization associated: "
                f"{existing_idp_tenant_id}"
            ),
            details={"idp_tenant_id": existing_idp_tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class SlugExhaustedError(UcpError):
    code: UcpErrorCode = UcpErrorCode.SLUG_EXHAUSTED

    @classmethod
    def for_name(cls, name: str, max_attempts: int) -> SlugExhaustedError:
        return cls(
            message=(
                f"Could not allocate a unique slug for tenant name {name!r} "
                f"after {max_attempts} attempts."
            ),
            details={"name": name, "max_attempts": max_attempts},
        )


@dataclass(frozen=True, kw_only=True)
class TenantInactiveForSubscriptionError(UcpError):
    code: UcpErrorCode = UcpErrorCode.TENANT_INACTIVE_FOR_SUBSCRIPTION
    message: str = "Cannot subscribe an inactive tenant to an app."


@dataclass(frozen=True, kw_only=True)
class AppNotFoundError(UcpError):
    app_id: str = ""
    code: UcpErrorCode = UcpErrorCode.APP_NOT_FOUND

    @classmethod
    def for_id(cls, app_id: str) -> AppNotFoundError:
        return cls(
            app_id=app_id,
            message=f"App {app_id} not found.",
            details={"app_id": app_id},
        )


@dataclass(frozen=True, kw_only=True)
class AppAlreadySubscribedError(UcpError):
    app_id: str = ""
    code: UcpErrorCode = UcpErrorCode.APP_ALREADY_SUBSCRIBED

    @classmethod
    def for_app(cls, app_id: str) -> AppAlreadySubscribedError:
        return cls(
            app_id=app_id,
            message=f"Tenant is already subscribed to '{app_id}'.",
            details={"app_id": app_id},
        )


@dataclass(frozen=True, kw_only=True)
class AppNotSubscribedError(UcpError):
    app_id: str = ""
    code: UcpErrorCode = UcpErrorCode.APP_NOT_SUBSCRIBED

    @classmethod
    def for_app(cls, app_id: str) -> AppNotSubscribedError:
        return cls(
            app_id=app_id,
            message=f"Tenant is not subscribed to '{app_id}'.",
            details={"app_id": app_id},
        )


@dataclass(frozen=True, kw_only=True)
class UcpUserNotFoundError(UcpError):
    user_id: str = ""
    code: UcpErrorCode = UcpErrorCode.USER_NOT_FOUND

    @classmethod
    def for_tenant_user(cls, user_id: str, tenant_id: str) -> UcpUserNotFoundError:
        return cls(
            user_id=user_id,
            message=f"User {user_id} not found or missing IDP mapping in tenant {tenant_id}",
            details={"user_id": user_id, "tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class UserStateConflictError(UcpError):
    code: UcpErrorCode = UcpErrorCode.USER_STATE_CONFLICT


@dataclass(frozen=True, kw_only=True)
class UcpRoleNotFoundError(UcpError):
    role_id: str = ""
    code: UcpErrorCode = UcpErrorCode.ROLE_NOT_FOUND

    @classmethod
    def for_id(cls, role_id: str, message: str | None = None) -> UcpRoleNotFoundError:
        return cls(
            role_id=role_id,
            message=message or f"Role '{role_id}' not found.",
            details={"role_id": role_id},
        )


@dataclass(frozen=True, kw_only=True)
class InvalidCapabilityValueError(UcpError):
    capability: str = ""
    code: UcpErrorCode = UcpErrorCode.INVALID_CAPABILITY

    @classmethod
    def for_capability(cls, capability: str) -> InvalidCapabilityValueError:
        return cls(
            capability=capability,
            message=f"Invalid capability: {capability}",
            details={"capability": capability},
        )


@dataclass(frozen=True, kw_only=True)
class WebhookNotFoundError(UcpError):
    webhook_id: str = ""
    code: UcpErrorCode = UcpErrorCode.WEBHOOK_NOT_FOUND

    @classmethod
    def for_id(cls, webhook_id: str, tenant_id: str | None = None) -> WebhookNotFoundError:
        msg = (
            f"Webhook {webhook_id} not found for tenant {tenant_id}"
            if tenant_id
            else f"Webhook {webhook_id} not found"
        )
        return cls(
            webhook_id=webhook_id,
            message=msg,
            details={"webhook_id": webhook_id},
        )


@dataclass(frozen=True, kw_only=True)
class WebhookAlreadyDeletedError(UcpError):
    webhook_id: str = ""
    code: UcpErrorCode = UcpErrorCode.WEBHOOK_ALREADY_DELETED

    @classmethod
    def for_id(cls, webhook_id: str) -> WebhookAlreadyDeletedError:
        return cls(
            webhook_id=webhook_id,
            message=f"Webhook '{webhook_id}' has already been deleted.",
            details={"webhook_id": webhook_id},
        )


@dataclass(frozen=True, kw_only=True)
class TokenNotFoundUcpError(UcpError):
    token_id: str = ""
    code: UcpErrorCode = UcpErrorCode.TOKEN_NOT_FOUND

    @classmethod
    def for_id(cls, token_id: str) -> TokenNotFoundUcpError:
        return cls(
            token_id=token_id,
            message="Token not found",
            details={"token_id": token_id},
        )


@dataclass(frozen=True, kw_only=True)
class TokenStateConflictError(UcpError):
    code: UcpErrorCode = UcpErrorCode.TOKEN_STATE_CONFLICT


# ---------------------------------------------------------------------------
# Infrastructure / Persistence Boundary Exceptions
# ---------------------------------------------------------------------------


class DomainError(Exception):
    """Base exception for persistence/adapter boundary invariants."""


class ResourceNotFoundError(DomainError):
    """Raised by database persistence adapters on missing FK targets."""


class StateConflictError(DomainError):
    """Raised by persistence adapters when DB constraints conflict."""


class IdempotencyConflictError(DomainError):
    """Raised when an idempotency key lock is already held in-progress."""


class InvalidTenantNameError(DomainError):
    """Raised by pure slug utility when called synchronously outside Result flow."""


class InfrastructureError(Exception):
    """Base exception for external infrastructure and adapter errors."""


class IdentityProviderPortError(InfrastructureError):
    """Raised when the external Identity Provider fails."""

    def __init__(
        self, message: str, original_error: str | None = None, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.status_code = status_code


__all__ = [
    "AppAlreadySubscribedError",
    "AppNotFoundError",
    "AppNotSubscribedError",
    "DomainError",
    "EmptyTenantNameError",
    "IdempotencyConflictError",
    "IdentityProviderPortError",
    "IdpOrganizationConflictError",
    "InfrastructureError",
    "InvalidCapabilityValueError",
    "InvalidTenantNameError",
    "InvalidTenantSlugError",
    "MissingIdpOrganizationError",
    "ResourceNotFoundError",
    "Result",
    "SlugExhaustedError",
    "StateConflictError",
    "TenantAlreadyDeletedError",
    "TenantInactiveForSubscriptionError",
    "TenantNotFoundError",
    "TokenNotFoundUcpError",
    "TokenStateConflictError",
    "UcpError",
    "UcpErrorCode",
    "UcpRoleNotFoundError",
    "UcpUserNotFoundError",
    "UcpValidationError",
    "UserStateConflictError",
    "WebhookAlreadyDeletedError",
    "WebhookNotFoundError",
]
