from dataclasses import dataclass

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider
from ucp.ports.outbound.user_repository import IUserRepository


@dataclass(frozen=True)
class DeleteUserCommand:
    tenant_id: str
    user_id: str


class DeleteUserUseCase:
    def __init__(
        self,
        tenant_repo: ITenantRepository,
        user_repo: IUserRepository,
        user_identity_provider: IUserIdentityProvider,
    ):
        self._tenant_repo = tenant_repo
        self._user_repo = user_repo
        self._idp = user_identity_provider

    async def execute(self, command: DeleteUserCommand) -> None:
        tenant_users = await self._user_repo.find_users_by_tenant(command.tenant_id)
        user = next((u for u in tenant_users if u.id == command.user_id), None)

        if not user or not user.idp_user_id:
            raise ResourceNotFoundError(
                f"User {command.user_id} not found or missing IDP mapping in tenant {command.tenant_id}"
            )

        # 1. Remove tenant membership first
        await self._user_repo.remove_tenant_membership(command.tenant_id, command.user_id)

        # 2. Check if user has any remaining memberships
        has_memberships = await self._user_repo.has_any_tenant_memberships(command.user_id)

        # 3. Only delete user (IDP and local DB) if orphaned
        if not has_memberships:
            await self._idp.delete_user(user.idp_user_id)
            await self._user_repo.delete_orphaned_users([command.user_id])
