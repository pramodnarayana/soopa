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
            tenant_users = await self._uow.user_repo.find_users_by_tenant(command.tenant_id)
            user = next((u for u in tenant_users if u.id == command.user_id), None)

            if not user or not user.idp_user_id:
                raise ResourceNotFoundError(
                    f"User {command.user_id} not found or missing IDP mapping in tenant {command.tenant_id}"
                )

            # 1. Remove tenant membership first
            await self._uow.user_repo.remove_tenant_membership(command.tenant_id, command.user_id)

            # 2. Check if user has any remaining memberships
            has_memberships = await self._uow.user_repo.has_any_tenant_memberships(command.user_id)

            # 3. Only delete user locally and register outbox event if orphaned
            if not has_memberships:
                await self._uow.user_repo.delete_orphaned_users([command.user_id])

                self._uow.register_event(
                    event_type="UserDeleted",
                    payload={"idp_user_id": user.idp_user_id},
                    tenant_id=command.tenant_id,
                )

            await self._uow.commit()
