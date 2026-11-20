"""Use case for toggling the activation state of a Stitch."""

from __future__ import annotations

from dataclasses import dataclass

from ip.engine.application.use_cases.stitch.dtos import StitchSummaryDTO
from ip.engine.application.use_cases.stitch.update_stitch_use_case import (
    UpdateStitchCommand,
    UpdateStitchUseCase,
)
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchCatalogRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort


@dataclass(frozen=True)
class ToggleStitchStateCommand:
    """Command to toggle the activation state (ACTIVE / PAUSED) of a Stitch."""

    tenant_id: str
    stitch_id: str
    is_active: bool


class ToggleStitchStateUseCase:
    """Toggles the trigger state (ACTIVE / PAUSED) of a Stitch."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._uow = uow

    async def execute(self, command: ToggleStitchStateCommand) -> Result[StitchSummaryDTO, IpError]:
        use_case = UpdateStitchUseCase(
            stitch_catalog=self._stitch_catalog,
            uow=self._uow,
        )
        return await use_case.execute(
            UpdateStitchCommand(
                tenant_id=command.tenant_id,
                stitch_id=command.stitch_id,
                is_active=command.is_active,
            )
        )


__all__ = [
    "ToggleStitchStateCommand",
    "ToggleStitchStateUseCase",
]
