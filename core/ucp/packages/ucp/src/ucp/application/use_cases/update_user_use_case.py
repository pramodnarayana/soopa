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

            tenant_users = await self._uow.user_repo.find_users_by_tenant(command.tenant_id)
            user = next((u for u in tenant_users if u.id == command.user_id), None)

            if not user or not user.idp_user_id:
                raise ResourceNotFoundError(
                    f"User {command.user_id} not found or missing IDP mapping in tenant {command.tenant_id}"
                )

            # 1. Update Local User Domain Object
            user.name = f"{command.first_name} {command.last_name}".strip()
            await self._uow.user_repo.save(user)

            # 2. Update Tenant Membership Role
            await self._uow.user_repo.save_tenant_membership(
                tenant_id=tenant.id,
                user_id=user.id,
                role=command.role,
            )

            # 3. Register Outbox Event to Update IDP
            self._uow.register_event(
                event_type="UserUpdated",
                payload={
                    "idp_user_id": user.idp_user_id,
                    "org_id": tenant.idp_tenant_id,
                    "first_name": command.first_name,
                    "last_name": command.last_name,
                    "role": command.role,
                },
                tenant_id=tenant.id,
            )

            await self._uow.commit()
