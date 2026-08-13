from dataclasses import dataclass
from typing import Literal

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.uow import UcpUnitOfWorkPort


@dataclass(frozen=True)
class ToggleUserStatusCommand:
    tenant_id: str
    user_id: str
    action: Literal["activate", "deactivate"]


class ToggleUserStatusUseCase:
    def __init__(
        self,
        uow: UcpUnitOfWorkPort,
    ):
        self._uow = uow

    async def execute(self, command: ToggleUserStatusCommand) -> None:
        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant or not tenant.idp_tenant_id:
                raise ResourceNotFoundError(
                    f"Tenant {command.tenant_id} not found or missing IDP organization"
                )

            tenant_users = await self._uow.user_repo.find_users_by_tenant(command.tenant_id)
            user = next((u for u in tenant_users if u.id == command.user_id), None)

            if not user or not user.idp_user_id:
                raise ResourceNotFoundError(f"User mapping not found for {command.user_id}")

            # 1. Update local domain object state
            if command.action == "activate":
                user.activate()
            else:
                user.deactivate()

            await self._uow.user_repo.save(user)

            # 2. Register Outbox Event to Toggle IDP Status
            self._uow.register_event(
                event_type="UserStatusToggled",
                payload={
                    "idp_user_id": user.idp_user_id,
                    "org_id": tenant.idp_tenant_id,
                    "action": command.action,
                },
                tenant_id=tenant.id,
            )

            await self._uow.commit()
