from dataclasses import dataclass

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.uow import UcpUnitOfWorkPort


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
        uow: UcpUnitOfWorkPort,
    ):
        self._uow = uow

    async def execute(self, command: UpdateUserCommand) -> None:
        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                raise ResourceNotFoundError(f"Tenant {command.tenant_id} not found")

            if not tenant.idp_tenant_id:
                raise ValueError(f"Tenant {command.tenant_id} has no associated IDP organization")

            user = await self._uow.user_repo.find_by_id_and_tenant(
                user_id=command.user_id, tenant_id=command.tenant_id
            )

            if not user or not user.idp_user_id:
                raise ResourceNotFoundError(
                    f"User {command.user_id} not found or missing IDP mapping in tenant {command.tenant_id}"
                )

            # 1. Update Local User Domain Object & Register Outbox Event
            user.update_profile(
                first_name=command.first_name,
                last_name=command.last_name,
                tenant_id=command.tenant_id,
                role=command.role,
            )
            await self._uow.user_repo.save(user)

            # 2. Update Tenant Membership Role using PBAC
            pbac_role_name = command.role

            pbac_role = await self._uow.role_repo.get_global_role_by_name(pbac_role_name)
            if not pbac_role:
                raise ResourceNotFoundError(
                    f"Global PBAC Role '{pbac_role_name}' is not seeded in the database."
                )

            # Remove existing role mappings for the user in this tenant
            await self._uow.role_repo.remove_user_roles(tenant_id=tenant.id, user_id=user.id)

            # Persist local database role mapping
            await self._uow.role_repo.assign_user_role(
                tenant_id=tenant.id, user_id=user.id, role_id=pbac_role.id
            )

            # Emit domain event so outbox worker can sync to IdP
            user.assign_role(role_id=pbac_role.id, role_name=pbac_role.name, tenant_id=tenant.id)
            # Save again to flush the assign_role event to outbox
            await self._uow.user_repo.save(user)

            await self._uow.commit()
