"""Use case for deleting a Stitch from the Control Plane."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.domain.exceptions import IpError, Result, StitchNotFoundError
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchCatalogRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DeleteStitchCommand:
    """Command to permanently delete a Stitch and unregister it from runtime dispatch."""

    tenant_id: str
    stitch_id: str


class DeleteStitchUseCase:
    """Permanently deletes a Stitch from the Control Plane and unregisters it from memory."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._uow = uow

    async def execute(self, command: DeleteStitchCommand) -> Result[None, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            stitch_id=command.stitch_id,
        )
        bound.info("delete_stitch.received")

        deleted = False
        if self._uow is not None:
            async with self._uow:
                existing = await self._uow.stitches.get_by_id(
                    tenant_id=command.tenant_id,
                    stitch_id=command.stitch_id,
                )
                if existing is not None:
                    existing.mark_deleted()
                    await self._uow.stitches.delete(
                        tenant_id=command.tenant_id,
                        stitch_id=command.stitch_id,
                    )
                    await self._uow.commit()
                    deleted = True

        in_mem = self._stitch_catalog.get_stitch(
            tenant_id=command.tenant_id,
            stitch_id=command.stitch_id,
        )
        if in_mem is not None:
            self._stitch_catalog.unregister_stitch(
                tenant_id=command.tenant_id,
                stitch_id=command.stitch_id,
            )
            deleted = True

        if not deleted:
            bound.error("delete_stitch.not_found")
            return Result.err(StitchNotFoundError.for_id(command.stitch_id))

        bound.info("delete_stitch.completed", stitch_id=command.stitch_id)
        return Result.ok(None)


__all__ = [
    "DeleteStitchCommand",
    "DeleteStitchUseCase",
]
