"""Use case for updating mutable Stitch properties."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonPrimitive

from ip.engine.application.use_cases.stitch.dtos import StitchSummaryDTO, to_stitch_dto
from ip.engine.domain.exceptions import IpError, Result, StitchNotFoundError
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchCatalogRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateStitchCommand:
    """Command to update mutable Stitch properties (name, description, mapping_spec_id, filters, state)."""

    tenant_id: str
    stitch_id: str
    name: str | None = None
    description: str | None = None
    mapping_spec_id: str | None = None
    filter_conditions: Mapping[str, JsonPrimitive] | None = None
    is_active: bool | None = None


class UpdateStitchUseCase:
    """Updates mutable configuration or activation state of an existing Stitch."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._uow = uow

    async def execute(self, command: UpdateStitchCommand) -> Result[StitchSummaryDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            stitch_id=command.stitch_id,
        )
        bound.info("update_stitch.received")

        stitch: Stitch | None = None
        if self._uow is not None:
            async with self._uow:
                stitch = await self._uow.stitches.get_by_id(
                    tenant_id=command.tenant_id,
                    stitch_id=command.stitch_id,
                )
                if stitch is not None:
                    stitch.update_metadata(
                        name=command.name,
                        description=command.description,
                        mapping_spec_id=command.mapping_spec_id,
                        filter_conditions=command.filter_conditions,
                        is_active=command.is_active,
                    )
                    await self._uow.stitches.save(stitch)
                    await self._uow.commit()

        if stitch is None:
            stitch = self._stitch_catalog.get_stitch(
                tenant_id=command.tenant_id,
                stitch_id=command.stitch_id,
            )
            if stitch is None:
                bound.error("update_stitch.not_found")
                return Result.err(StitchNotFoundError.for_id(command.stitch_id))

            stitch.update_metadata(
                name=command.name,
                description=command.description,
                mapping_spec_id=command.mapping_spec_id,
                filter_conditions=command.filter_conditions,
                is_active=command.is_active,
            )

        self._stitch_catalog.register_stitch(stitch)
        bound.info(
            "update_stitch.completed",
            stitch_id=stitch.id,
            is_active=stitch.is_active,
            mapping_spec_id=stitch.mapping_spec_id,
        )
        return Result.ok(to_stitch_dto(stitch))


__all__ = [
    "UpdateStitchCommand",
    "UpdateStitchUseCase",
]
