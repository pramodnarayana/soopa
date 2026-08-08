from dataclasses import dataclass
from typing import Literal

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider
from ucp.ports.outbound.user_repository import IUserRepository


@dataclass(frozen=True)
class ToggleUserStatusCommand:
    tenant_id: str
    user_id: str
    action: Literal["activate", "deactivate"]


class ToggleUserStatusUseCase:
    def __init__(
        self,
        tenant_repo: ITenantRepository,
        user_repo: IUserRepository,
        user_identity_provider: IUserIdentityProvider,
    ):
        self._tenant_repo = tenant_repo
        self._user_repo = user_repo
        self._idp = user_identity_provider

    async def execute(self, command: ToggleUserStatusCommand) -> None:
        tenant = await self._tenant_repo.find_by_id(command.tenant_id)
        if not tenant or not tenant.idp_tenant_id:
            raise ResourceNotFoundError(
                f"Tenant {command.tenant_id} not found or missing IDP organization"
            )

        tenant_users = await self._user_repo.find_users_by_tenant(command.tenant_id)
        user = next((u for u in tenant_users if u.id == command.user_id), None)

        if not user or not user.idp_user_id:
            raise ResourceNotFoundError(f"User mapping not found for {command.user_id}")

        # 1. Toggle status in IDP
        await self._idp.toggle_user_status(
            user_id=user.idp_user_id,
            org_id=tenant.idp_tenant_id,
            action=command.action,
        )

        # 2. Update local domain object state
        if command.action == "activate":
            user.activate()
        else:
            user.deactivate()

        await self._user_repo.save(user)
