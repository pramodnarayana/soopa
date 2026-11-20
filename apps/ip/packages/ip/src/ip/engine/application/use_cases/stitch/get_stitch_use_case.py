"""Use case for retrieving a single Stitch by ID for a tenant."""

from __future__ import annotations

from dataclasses import dataclass

from ip.engine.application.use_cases.stitch.dtos import StitchSummaryDTO, to_stitch_dto
from ip.engine.domain.exceptions import IpError, Result, StitchNotFoundError
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchCatalogRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort


@dataclass(frozen=True)
class GetStitchQuery:
    """Query to fetch a single Stitch by ID for a tenant."""

    tenant_id: str
    stitch_id: str


class GetStitchUseCase:
    """Retrieves a single Stitch by ID for a tenant."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._uow = uow

    async def execute(self, query: GetStitchQuery) -> Result[StitchSummaryDTO, IpError]:
        if self._uow is not None:
            async with self._uow:
                stitch = await self._uow.stitches.get_by_id(
                    tenant_id=query.tenant_id,
                    stitch_id=query.stitch_id,
                )
                if stitch is not None:
                    return Result.ok(to_stitch_dto(stitch))

        in_mem = self._stitch_catalog.get_stitch(
            tenant_id=query.tenant_id,
            stitch_id=query.stitch_id,
        )
        if in_mem is not None:
            return Result.ok(to_stitch_dto(in_mem))

        return Result.err(StitchNotFoundError.for_id(query.stitch_id))


__all__ = [
    "GetStitchQuery",
    "GetStitchUseCase",
]
