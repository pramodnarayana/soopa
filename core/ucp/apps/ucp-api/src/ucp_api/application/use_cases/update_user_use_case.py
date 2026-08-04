from dataclasses import dataclass

from ucp_api.core.exceptions import ResourceNotFoundError
from ucp_api.ports.outbound.tenant_repository import ITenantRepository
from ucp_api.ports.outbound.user_identity_provider import IUserIdentityProvider
from ucp_api.ports.outbound.user_repository import IUserRepository


@dataclass(frozen=True)
class UpdateUserCommand:
    tenant_id: str
    user_id: str
    first_name: str
    last_name: str
    role: str


class UpdateUserUseCase:
    def __init__(
        self,
        tenant_repo: ITenantRepository,
        user_repo: IUserRepository,
        user_identity_provider: IUserIdentityProvider,
    ):
        self._tenant_repo = tenant_repo
        self._user_repo = user_repo
        self._idp = user_identity_provider

    async def execute(self, command: UpdateUserCommand) -> None:
        tenant = await self._tenant_repo.find_by_id(command.tenant_id)
        if not tenant:
            raise ResourceNotFoundError(f"Tenant {command.tenant_id} not found")

        if not tenant.idp_tenant_id:
            raise ValueError(f"Tenant {command.tenant_id} has no associated IDP organization")

        tenant_users = await self._user_repo.find_users_by_tenant(command.tenant_id)
        user = next((u for u in tenant_users if u.id == command.user_id), None)

        if not user or not user.idp_user_id:
            raise ResourceNotFoundError(
                f"User {command.user_id} not found or missing IDP mapping in tenant {command.tenant_id}"
            )

        # 1. Update Profile in IDP
        await self._idp.update_user_profile(
            user_id=user.idp_user_id,
            org_id=tenant.idp_tenant_id,
            first_name=command.first_name,
            last_name=command.last_name,
        )

        # 2. Update Role in IDP
        await self._idp.update_tenant_role(
            user_id=user.idp_user_id,
            org_id=tenant.idp_tenant_id,
            role=command.role,
        )

        # 3. Update Local User Domain Object
        user.name = f"{command.first_name} {command.last_name}".strip()
        await self._user_repo.save(user)

        # 4. Update Tenant Membership Role
        await self._user_repo.save_tenant_membership(
            tenant_id=tenant.id,
            user_id=user.id,
            role=command.role,
        )
