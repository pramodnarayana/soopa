from dataclasses import dataclass

from ucp.domain.exceptions import ResourceNotFoundError
from ucp.ports.outbound.uow import UcpUnitOfWorkPort


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

            # 1. The aggregate handles its own invariant checks and event emissions
            user.remove_membership(command.tenant_id)

            # 2. The repository translates the state to the DB and flushes events
            await self._uow.role_repo.remove_user_roles(
                tenant_id=command.tenant_id, user_id=user.id
            )
            # Re-save the user to flush domain events
            await self._uow.user_repo.save(user)

            # 3. Check if user is fully orphaned
            has_memberships = await self._uow.role_repo.has_any_tenant_memberships(user.id)
            if not has_memberships:
                user.mark_deleted()
                await self._uow.user_repo.delete(user)

            await self._uow.commit()
