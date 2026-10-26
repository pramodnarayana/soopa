"""PromoteMappingVersionUseCase: Promotes candidate shadow mapper version to active."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from ip.engine.domain.enums import MappingMode
from ip.engine.domain.events import MappingVersionPromotedEvent
from ip.engine.domain.exceptions import (
    IpError,
    MappingBindingNotFoundError,
    NormalizationFailedError,
    Result,
)
from ip.engine.domain.normalization import MappingBinding
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PromoteMappingVersionCommand:
    """Command to promote shadow mapper version to active."""

    tenant_id: str
    connection_id: str
    stream: str


@dataclass(frozen=True)
class PromoteMappingVersionResultDTO:
    """Result of mapping version promotion."""

    binding_id: str
    connection_id: str
    stream: str
    mapping_id: str
    promoted_version: int
    previous_version: int


class PromoteMappingVersionUseCase:
    """Use case promoting a candidate shadow mapping version to active production status."""

    def __init__(self, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = control_plane_uow

    async def execute(
        self, command: PromoteMappingVersionCommand
    ) -> Result[PromoteMappingVersionResultDTO, IpError]:
        """Promote shadow version to active, clearing shadow version and emitting event."""
        bound_logger = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
        )

        binding = await self._uow.mapping_bindings.get_by_stream(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
        )
        if binding is None:
            return Result.err(
                MappingBindingNotFoundError.for_stream(
                    connection_id=command.connection_id,
                    stream=command.stream,
                )
            )

        if binding.shadow_mapping_version is None:
            return Result.err(
                NormalizationFailedError.with_message(
                    f"No candidate shadow_mapping_version configured on binding '{binding.id}' to promote."
                )
            )

        previous_version = binding.mapping_version
        promoted_version = binding.shadow_mapping_version

        updated_binding = MappingBinding(
            id=binding.id,
            tenant_id=binding.tenant_id,
            connection_id=binding.connection_id,
            stream=binding.stream,
            mapping_id=binding.mapping_id,
            mapping_version=promoted_version,
            mode=MappingMode.ACTIVE,
            shadow_mapping_version=None,
            created_at=binding.created_at,
            updated_at=datetime.now(UTC),
        )

        updated_binding.add_domain_event(
            MappingVersionPromotedEvent(
                binding_id=updated_binding.id,
                tenant_id=updated_binding.tenant_id,
                connection_id=updated_binding.connection_id,
                stream=updated_binding.stream,
                mapping_id=updated_binding.mapping_id,
                promoted_version=promoted_version,
                previous_version=previous_version,
            )
        )

        await self._uow.mapping_bindings.save(updated_binding)
        await self._uow.commit()

        bound_logger.info(
            "mapping_version_promoted",
            binding_id=updated_binding.id,
            previous_version=previous_version,
            promoted_version=promoted_version,
        )

        return Result.ok(
            PromoteMappingVersionResultDTO(
                binding_id=updated_binding.id,
                connection_id=updated_binding.connection_id,
                stream=updated_binding.stream,
                mapping_id=updated_binding.mapping_id,
                promoted_version=promoted_version,
                previous_version=previous_version,
            )
        )
