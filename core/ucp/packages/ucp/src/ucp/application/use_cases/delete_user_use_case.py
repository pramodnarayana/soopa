from dataclasses import dataclass

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.uow import UcpUnitOfWorkPort


@dataclass(frozen=True)
class DeleteUserCommand:
    tenant_id: str
    user_id: str


class DeleteUserUseCase:
    def __init__(
        self,
        uow: UcpUnitOfWorkPort,
    ):
        self._uow = uow

    async def execute(self, command: DeleteUserCommand) -> None:
        async with self._uow:
            user = await self._uow.user_repo.find_by_id_and_tenant(
                command.user_id, command.tenant_id
            )

            if not user or not user.idp_user_id:
                raise ResourceNotFoundError(
                    f"User {command.user_id} not found or missing IDP mapping in tenant {command.tenant_id}"
                )

            # Resolve tenant to get idp_tenant_id for the event
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                raise ResourceNotFoundError(f"Tenant {command.tenant_id} not found")

            # 1. The aggregate handles its own invariant checks and event emissions
            user.remove_membership(tenant.idp_tenant_id or command.tenant_id)

            # 2. The repository translates the state to the DB and flushes events
            await self._uow.user_repo.remove_tenant_membership(command.tenant_id, user)

            # 3. Check if user is fully orphaned
            has_memberships = await self._uow.user_repo.has_any_tenant_memberships(user.id)
            if not has_memberships:
                user.mark_deleted()
                await self._uow.user_repo.delete(user)

            await self._uow.commit()
