import os
from dataclasses import dataclass

import structlog
from identity.domain.events import UserCreatedEvent
from identity.domain.models.user import User

from ucp.domain.exceptions import ResourceNotFoundError, StateConflictError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


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
        logger.info(
            "create_user.started",
            tenant_id=command.tenant_id,
            role=command.role,
        )
        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                logger.error("create_user.tenant_not_found", tenant_id=command.tenant_id)
                raise ResourceNotFoundError(f"Tenant {command.tenant_id} not found")

            if not tenant.idp_tenant_id:
                logger.error("create_user.missing_idp_tenant", tenant_id=command.tenant_id)
                raise StateConflictError(
                    f"Tenant {command.tenant_id} has no associated IDP organization"
                )

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

            # 2. Assign PBAC Role
            pbac_role = await self._uow.role_repo.get_global_role_by_name(command.role)
            if not pbac_role:
                raise ResourceNotFoundError(
                    f"Global PBAC Role '{command.role}' is not found in the database."
                )

            # Emit the domain event for external sync
            new_user.assign_role(
                role_id=pbac_role.id, role_name=pbac_role.name, tenant_id=tenant.id
            )

            # Re-save the user to persist PBAC role event outbox flush
            await self._uow.user_repo.save(new_user)

            # Persist local database role mapping
            await self._uow.role_repo.assign_user_role(
                tenant_id=tenant.id, user_id=local_user_id, role_id=pbac_role.id
            )

            # 3. Register Outbox Event to Create in IDP
            new_user.add_domain_event(
                UserCreatedEvent(
                    user_id=local_user_id,
                    tenant_id=tenant.id,
                    email=command.email,
                    first_name=command.first_name,
                    last_name=command.last_name,
                    role=command.role,
                )
            )
            # Re-save the user to persist PBAC role and flush the event outbox
            await self._uow.user_repo.save(new_user)

            await self._uow.commit()

            logger.info(
                "create_user.completed",
                tenant_id=tenant.id,
                user_id=local_user_id,
            )
            return local_user_id
