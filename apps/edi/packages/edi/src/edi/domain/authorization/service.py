"""EDI Domain Authorization Policy and Value Objects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from edi.domain.authorization.tenant import TenantFeatureFlags
from edi.domain.types import JsonDict, JsonValue


class EdiAuthorizationRole(StrEnum):
    """Canonical RBAC role tier within the EDI bounded context."""

    OWNER = "Owner"
    ADMIN = "Admin"
    STANDARD = "Standard"


class EdiPermission(StrEnum):
    """Granular capability permissions evaluated by AuthorizationPolicy."""

    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_DELETE = "users:delete"
    ROUTES_MANAGE = "routes:manage"
    CERTIFICATES_EXPORT_PRIVATE = "certificates:export_private"
    CERTIFICATES_ROTATE = "certificates:rotate"


_MANAGEMENT_PERMISSIONS: tuple[EdiPermission, ...] = (
    EdiPermission.USERS_READ,
    EdiPermission.USERS_WRITE,
    EdiPermission.USERS_DELETE,
    EdiPermission.ROUTES_MANAGE,
    EdiPermission.CERTIFICATES_EXPORT_PRIVATE,
    EdiPermission.CERTIFICATES_ROTATE,
)

_STANDARD_PERMISSIONS: tuple[EdiPermission, ...] = (EdiPermission.USERS_READ,)

_ELEVATED_IDP_ROLES: frozenset[str] = frozenset({"owner", "admin"})


@dataclass(frozen=True, kw_only=True)
class AuthorizationProfile:
    """Resolved EDI RBAC profile and tenant feature gates."""

    tenant_id: str
    is_platform_admin: bool
    allow_private_as2: bool
    role: EdiAuthorizationRole
    permissions: tuple[EdiPermission, ...]
    rls_enforced_tenant: str | None

    def to_dict(self) -> JsonDict:
        """Serialize the authorization profile for inbound HTTP boundary consumers."""
        permission_values: list[JsonValue] = [perm.value for perm in self.permissions]
        return {
            "status": "success",
            "tenant_id": self.tenant_id,
            "is_platform_admin": self.is_platform_admin,
            "allow_private_as2": self.allow_private_as2,
            "role": self.role.value,
            "permissions": permission_values,
            "rls_enforced_tenant": self.rls_enforced_tenant,
        }


class AuthorizationPolicy:
    """Pure synchronous domain policy for EDI role and feature-gate resolution."""

    @staticmethod
    def evaluate(
        *,
        tenant_id: str,
        is_platform_admin: bool,
        current_rls_tenant: str | None,
        roles: Sequence[str] | None = None,
        tenant_flags: TenantFeatureFlags | None = None,
    ) -> AuthorizationProfile:
        """Evaluate role, granular permissions, and feature flags with zero I/O."""
        normalized_roles = roles or ()
        allow_private_as2 = tenant_flags.allow_private_as2 if tenant_flags is not None else False

        if is_platform_admin:
            role = EdiAuthorizationRole.OWNER
        elif any(r.lower() in _ELEVATED_IDP_ROLES for r in normalized_roles):
            role = EdiAuthorizationRole.ADMIN
        else:
            role = EdiAuthorizationRole.STANDARD

        permissions = (
            _MANAGEMENT_PERMISSIONS
            if role in (EdiAuthorizationRole.OWNER, EdiAuthorizationRole.ADMIN)
            else _STANDARD_PERMISSIONS
        )

        return AuthorizationProfile(
            tenant_id=tenant_id,
            is_platform_admin=is_platform_admin,
            allow_private_as2=allow_private_as2,
            role=role,
            permissions=permissions,
            rls_enforced_tenant=current_rls_tenant,
        )


__all__ = [
    "AuthorizationPolicy",
    "AuthorizationProfile",
    "EdiAuthorizationRole",
    "EdiPermission",
]
