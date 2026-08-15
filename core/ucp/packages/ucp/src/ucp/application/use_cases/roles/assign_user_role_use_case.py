import structlog
from platform_orm.models import Role as OrmRole
from platform_orm.models import User as OrmUser
from pydantic import BaseModel
from sqlalchemy import select

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
            # Validate user belongs to the specified tenant
            user_stmt = select(OrmUser).where(OrmUser.id == request.user_id)
            user_result = await self.uow.session.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            if not user:
                raise ResourceNotFoundError(f"User '{request.user_id}' not found.")
            if user.tenant_id != tenant_id:
                raise ResourceNotFoundError(
                    f"User '{request.user_id}' does not belong to tenant '{tenant_id}'."
                )

            # Validate role exists and is scoped correctly
            role_stmt = select(OrmRole).where(OrmRole.id == request.role_id)
            role_result = await self.uow.session.execute(role_stmt)
            role = role_result.scalar_one_or_none()
            if not role:
                raise ResourceNotFoundError(f"Role '{request.role_id}' not found.")

            # Platform-wide roles (tenant_id is NULL) can be assigned to any user
            # Tenant-scoped roles must match the target tenant
            if role.tenant_id is not None and role.tenant_id != tenant_id:
                raise ResourceNotFoundError(
                    f"Role '{request.role_id}' is scoped to tenant '{role.tenant_id}' "
                    f"and cannot be assigned in tenant '{tenant_id}'."
                )

            await self.uow.role_repo.assign_user_role(
                tenant_id=tenant_id,
                user_id=request.user_id,
                role_id=request.role_id,
            )
            await self.uow.commit()

        bound_logger.info("assign_user_role.completed")
