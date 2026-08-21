from dataclasses import dataclass
from typing import Literal

from ucp.domain.exceptions import ResourceNotFoundError
from ucp.ports.outbound.uow import UcpUnitOfWorkPort


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

            user = await self._uow.user_repo.find_by_id_and_tenant(
                user_id=command.user_id, tenant_id=command.tenant_id
            )

            if not user or not user.idp_user_id:
                raise ResourceNotFoundError(f"User mapping not found for {command.user_id}")

            # 1. Update local domain object state & Register Outbox Event
            user.change_status(action=command.action, tenant_id=command.tenant_id)
            await self._uow.user_repo.save(user)

            await self._uow.commit()
