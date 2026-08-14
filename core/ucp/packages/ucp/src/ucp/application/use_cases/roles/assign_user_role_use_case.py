import structlog
from pydantic import BaseModel

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
            await self.uow.role_repo.assign_user_role(
                tenant_id=tenant_id,
                user_id=request.user_id,
                role_id=request.role_id,
            )
            await self.uow.commit()

        bound_logger.info("assign_user_role.completed")
