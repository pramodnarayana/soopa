import structlog
from identity.domain.models.authorization import Capability, Role
from seedwork import generate_id

from ucp.application.dto import CreateRoleRequest, CreateRoleResponse
from ucp.domain.exceptions import InvalidCapabilityError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class CreateRoleUseCase:
    """
    Creates a new custom role within a tenant.
    """

    def __init__(self, uow: UcpUnitOfWorkPort):
        self.uow = uow

    async def execute(
        self, tenant_id: str | None, request: CreateRoleRequest
    ) -> CreateRoleResponse:
        bound_logger = logger.bind(tenant_id=tenant_id, role_name=request.name)
        bound_logger.info("create_role.started")

        # Validate that the requested capabilities are valid predefined capabilities
        valid_capabilities = {cap.value for cap in Capability}
        for cap in request.capabilities:
            if cap not in valid_capabilities:
                bound_logger.error("create_role.invalid_capability", capability=cap)
                raise InvalidCapabilityError(f"Invalid capability: {cap}")

        async with self.uow:
            role = Role.create(
                id=generate_id("rol"),
                tenant_id=tenant_id,
                name=request.name,
                description=request.description,
                capabilities=request.capabilities,
            )
            await self.uow.role_repo.save(role)
            await self.uow.commit()

        bound_logger.info("create_role.completed", role_id=role.id)

        return CreateRoleResponse(
            id=role.id,
            name=role.name,
            capabilities=role.capabilities,
        )
