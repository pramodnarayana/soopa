import os
from dataclasses import dataclass

from ucp.core.exceptions import ResourceNotFoundError
from ucp.domain.models.user import User
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider
from ucp.ports.outbound.user_repository import IUserRepository


@dataclass(frozen=True)
class InviteUserCommand:
    tenant_id: str
    email: str
    first_name: str
    last_name: str
    role: str


class InviteUserUseCase:
    def __init__(
        self,
        tenant_repo: ITenantRepository,
        user_repo: IUserRepository,
        user_identity_provider: IUserIdentityProvider,
    ):
        self._tenant_repo = tenant_repo
        self._user_repo = user_repo
        self._idp = user_identity_provider

    async def execute(self, command: InviteUserCommand) -> str:
        tenant = await self._tenant_repo.find_by_id(command.tenant_id)
        if not tenant:
            raise ResourceNotFoundError(f"Tenant {command.tenant_id} not found")

        if not tenant.idp_tenant_id:
            raise ValueError(f"Tenant {command.tenant_id} has no associated IDP organization")

        # 1. Orchestrate creation in IDP
        idp_user_id = await self._idp.create_user(
            org_id=tenant.idp_tenant_id,
            email=command.email,
            first_name=command.first_name,
            last_name=command.last_name,
        )

        # 2. Grant role in IDP
        await self._idp.assign_tenant_role(
            user_id=idp_user_id,
            org_id=tenant.idp_tenant_id,
            role=command.role,
        )

        # 3. Create Local Domain User and Save
        local_user_id = f"{User.ID_PREFIX}_{os.urandom(12).hex()}"
        name = f"{command.first_name} {command.last_name}".strip()

        new_user = User.create(
            id=local_user_id,
            idp_user_id=idp_user_id,
            email=command.email,
            name=name,
        )
        await self._user_repo.save(new_user)

        # 4. Save Tenant Membership
        await self._user_repo.save_tenant_membership(
            tenant_id=tenant.id,
            user_id=local_user_id,
            role=command.role,
        )

        return local_user_id
