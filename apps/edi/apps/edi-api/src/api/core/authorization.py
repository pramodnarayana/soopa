from typing import Any

from api.ports.tenant_repository import TenantRepositoryPort


class AuthorizationService:
    def __init__(self, tenant_repo: TenantRepositoryPort) -> None:
        self.tenant_repo = tenant_repo

    async def get_authorization_profile(
        self,
        tenant_id: int,
        is_platform_admin: bool,
        current_rls_tenant: int | None,
        roles: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Calculates the user's roles, permissions, and feature flags without touching HTTP or SQLAlchemy.
        """
        roles = roles or []

        # Fetch Tenant feature flags using Port
        tenant_flags = await self.tenant_repo.get_tenant_flags(tenant_id)
        allow_private_as2 = tenant_flags.get("allow_private_as2", False) if tenant_flags else False

        # Map Role to Granular Permissions
        if is_platform_admin:
            role = "Owner"
        elif any(str(r).lower() in ["owner", "admin"] for r in roles):
            role = "Admin"
        else:
            role = "Standard"

        permissions = []

        if role in ["Owner", "Admin"]:
            permissions.extend(
                [
                    "users:read",
                    "users:write",
                    "users:delete",
                    "routes:manage",
                    "certificates:export_private",
                    "certificates:rotate",
                ]
            )
        else:
            permissions.extend(["users:read"])

        return {
            "status": "success",
            "tenant_id": tenant_id,
            "is_platform_admin": is_platform_admin,
            "allow_private_as2": allow_private_as2,
            "role": role,
            "permissions": permissions,
            "rls_enforced_tenant": current_rls_tenant,
        }
