import os
from dataclasses import dataclass

from ucp.core.exceptions import ResourceNotFoundError
from ucp.domain.events.user_events import UserCreatedEvent
from ucp.domain.models.user import User
from ucp.ports.uow import UcpUnitOfWorkPort


@dataclass(frozen=True)
class CreateUserCommand:
    tenant_id: str
    email: str
    first_name: str
    last_name: str
    role: str


class CreateUserUseCase:
    def __init__(
        self,
        uow: UcpUnitOfWorkPort,
    ):
        self._uow = uow

    async def execute(self, command: CreateUserCommand) -> str:
        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                raise ResourceNotFoundError(f"Tenant {command.tenant_id} not found")

            if not tenant.idp_tenant_id:
                raise ValueError(f"Tenant {command.tenant_id} has no associated IDP organization")

            # 1. Create Local Domain User and Save
            local_user_id = f"{User.ID_PREFIX}_{os.urandom(12).hex()}"
            name = f"{command.first_name} {command.last_name}".strip()

            new_user = User.create(
                id=local_user_id,
                idp_user_id=None,
                email=command.email,
                name=name,
            )
            await self._uow.user_repo.save(new_user)

            # 2. Save Tenant Membership
            await self._uow.user_repo.save_tenant_membership(
                tenant_id=tenant.id,
                user_id=local_user_id,
                role=command.role,
            )

            # 3. Register Outbox Event to Create in IDP
            new_user.add_domain_event(
                UserCreatedEvent(
                    org_id=tenant.idp_tenant_id,
                    email=command.email,
                    first_name=command.first_name,
                    last_name=command.last_name,
                    role=command.role,
                )
            )
            # Re-save the user to flush the event outbox
            await self._uow.user_repo.save(new_user)

            await self._uow.commit()

            return local_user_id
