from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from identity.domain.authorization import CapabilityDescriptor
from identity.domain.exceptions import IdentityError
from identity.ports.outbound.uow_port import IdentityUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ListCapabilitiesQuery:
    domain: str | None = None


class ListCapabilitiesUseCase:
    """
    Use case for querying the system-wide Capability Catalog.
    Provides data to the IAM Admin UI to render permission trees, checkboxes, and descriptions.
    """

    def __init__(self, uow: IdentityUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, query: ListCapabilitiesQuery
    ) -> Result[list[CapabilityDescriptor], IdentityError]:
        bound_logger = logger.bind(domain_filter=query.domain)
        bound_logger.info("list_capabilities.started")

        async with self.uow:
            if query.domain:
                capabilities = await self.uow.capability_repo.list_by_domain(query.domain)
            else:
                capabilities = await self.uow.capability_repo.list_all()

        bound_logger.info("list_capabilities.completed", count=len(capabilities))
        return Result.ok(capabilities)
