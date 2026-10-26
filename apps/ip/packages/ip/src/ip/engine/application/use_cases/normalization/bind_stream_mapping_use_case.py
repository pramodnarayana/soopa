"""BindStreamMappingUseCase: Configures stream to mapper version bindings in Control Plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from ip.engine.domain.enums import MappingMode
from ip.engine.domain.events import MappingBindingChangedEvent
from ip.engine.domain.exceptions import IpError, NormalizationFailedError, Result
from ip.engine.domain.normalization import MappingBinding
from ip.engine.ports.outbound.mapper_port import MapperRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BindStreamMappingCommand:
    """Command to bind a stream to a specific mapper version."""

    tenant_id: str
    connection_id: str
    stream: str
    mapping_id: str
    mapping_version: int
    mode: MappingMode = MappingMode.ACTIVE
    shadow_mapping_version: int | None = None


@dataclass(frozen=True)
class BindStreamMappingResultDTO:
    """Result of stream mapping binding operation."""

    binding_id: str
    connection_id: str
    stream: str
    mapping_id: str
    mapping_version: int
    mode: str
    shadow_mapping_version: int | None = None


class BindStreamMappingUseCase:
    """Use case configuring or updating stream mapping bindings in Control Plane."""

    def __init__(
        self,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        mapper_registry: MapperRegistryPort | None = None,
    ) -> None:
        self._uow = control_plane_uow
        self._mapper_registry = mapper_registry

    async def execute(
        self, command: BindStreamMappingCommand
    ) -> Result[BindStreamMappingResultDTO, IpError]:
        """Execute stream binding upsert and emit audit domain event."""
        bound_logger = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            mapping_id=command.mapping_id,
            mapping_version=command.mapping_version,
        )

        if self._mapper_registry is not None:
            if self._mapper_registry.get(command.mapping_id, command.mapping_version) is None:
                bound_logger.error(
                    "bind_stream_mapping_version_not_registered",
                    mapping_id=command.mapping_id,
                    mapping_version=command.mapping_version,
                )
                return Result.err(
                    NormalizationFailedError.with_message(
                        f"Mapper '{command.mapping_id}' version {command.mapping_version} is not registered."
                    )
                )
            if (
                command.shadow_mapping_version is not None
                and self._mapper_registry.get(command.mapping_id, command.shadow_mapping_version)
                is None
            ):
                bound_logger.error(
                    "bind_stream_shadow_mapping_version_not_registered",
                    mapping_id=command.mapping_id,
                    shadow_mapping_version=command.shadow_mapping_version,
                )
                return Result.err(
                    NormalizationFailedError.with_message(
                        f"Shadow mapper '{command.mapping_id}' version {command.shadow_mapping_version} is not registered."
                    )
                )

        existing = await self._uow.mapping_bindings.get_by_stream(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
        )

        if existing is None:
            binding = MappingBinding.create(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream,
                mapping_id=command.mapping_id,
                mapping_version=command.mapping_version,
                mode=command.mode,
                shadow_mapping_version=command.shadow_mapping_version,
            )
        else:
            binding = MappingBinding(
                id=existing.id,
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream,
                mapping_id=command.mapping_id,
                mapping_version=command.mapping_version,
                mode=command.mode,
                shadow_mapping_version=command.shadow_mapping_version,
                created_at=existing.created_at,
                updated_at=datetime.now(UTC),
            )

        binding.add_domain_event(
            MappingBindingChangedEvent(
                binding_id=binding.id,
                tenant_id=binding.tenant_id,
                connection_id=binding.connection_id,
                stream=binding.stream,
                mapping_id=binding.mapping_id,
                mapping_version=binding.mapping_version,
                mode=binding.mode.value,
                shadow_mapping_version=binding.shadow_mapping_version,
            )
        )

        await self._uow.mapping_bindings.save(binding)
        await self._uow.commit()

        bound_logger.info("stream_mapping_bound", binding_id=binding.id)

        return Result.ok(
            BindStreamMappingResultDTO(
                binding_id=binding.id,
                connection_id=binding.connection_id,
                stream=binding.stream,
                mapping_id=binding.mapping_id,
                mapping_version=binding.mapping_version,
                mode=binding.mode.value,
                shadow_mapping_version=binding.shadow_mapping_version,
            )
        )
