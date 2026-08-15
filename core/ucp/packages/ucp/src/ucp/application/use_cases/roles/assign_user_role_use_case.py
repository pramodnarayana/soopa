import structlog
from pydantic import BaseModel

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.uow import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class AssignUserRoleRequest(BaseModel):
    user_id: str
    role_id: str


class AssignUserRoleUseCase:
    """
    Assigns a role to a user within a tenant.
    """

    def __init__(self, uow: UcpUnitOfWorkPort):
        self.uow = uow

    async def execute(self, tenant_id: str | None, request: AssignUserRoleRequest) -> None:
        bound_logger = logger.bind(
            tenant_id=tenant_id, user_id=request.user_id, role_id=request.role_id
        )
        bound_logger.info("assign_user_role.started")

        async with self.uow:
            # Domain-Driven Design: Use Repository Ports to fetch aggregates, no ORM leakage.
            user = await self.uow.user_repo.find_by_id_and_tenant(request.user_id, tenant_id or "")
            if not user:
                raise ResourceNotFoundError(
                    f"User '{request.user_id}' not found in tenant '{tenant_id}'."
                )

            role = await self.uow.role_repo.get_by_id(request.role_id)
            if not role:
                raise ResourceNotFoundError(f"Role '{request.role_id}' not found.")

            # Platform-wide roles (tenant_id is NULL) can be assigned to any user
            # Tenant-scoped roles must match the target tenant
            if role.tenant_id is not None and role.tenant_id != tenant_id:
                raise ResourceNotFoundError(
                    f"Role '{request.role_id}' is scoped to tenant '{role.tenant_id}' "
                    f"and cannot be assigned in tenant '{tenant_id}'."
                )

            # Assign role via Aggregate Root to collect domain events
            user.assign_role(role.id)

            # Persist role assignment
            await self.uow.role_repo.assign_user_role(
                tenant_id=tenant_id,
                user_id=user.id,
                role_id=role.id,
            )

            # Persist aggregate (flushes events via outbox pattern)
            await self.uow.user_repo.save(user)
            await self.uow.commit()

        bound_logger.info("assign_user_role.completed")
