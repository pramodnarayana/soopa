"""Use case for listing all Stitches visible to a tenant."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.application.use_cases.stitch.dtos import StitchSummaryDTO, to_stitch_dto
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchCatalogRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ListStitchesQuery:
    """Query to list all Stitches active or registered for a tenant."""

    tenant_id: str


class ListStitchesUseCase:
    """Lists all Stitches visible to a tenant (PostgreSQL Control Plane + default wildcard catalog)."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._uow = uow

    async def execute(self, query: ListStitchesQuery) -> tuple[StitchSummaryDTO, ...]:
        merged: dict[str, Stitch] = {
            s.id: s for s in self._stitch_catalog.list_stitches(tenant_id=query.tenant_id)
        }
        if self._uow is not None:
            async with self._uow:
                db_stitches = await self._uow.stitches.list_by_tenant(tenant_id=query.tenant_id)
                for stitch in db_stitches:
                    merged[stitch.id] = stitch

        ordered = sorted(merged.values(), key=lambda s: s.id)
        dtos = tuple(to_stitch_dto(s) for s in ordered)
        logger.info(
            "list_stitches.completed",
            tenant_id=query.tenant_id,
            count=len(dtos),
        )
        return dtos


__all__ = [
    "ListStitchesQuery",
    "ListStitchesUseCase",
]
