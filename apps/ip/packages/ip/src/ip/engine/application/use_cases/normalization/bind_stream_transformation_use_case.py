"""BindStreamTransformationUseCase: Configures stream to transformer version configurations in Control Plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from ip.engine.domain.enums import TransformationMode
from ip.engine.domain.events import TransformationChangedEvent
from ip.engine.domain.exceptions import IpError, NormalizationFailedError, Result
from ip.engine.domain.normalization import Transformation
from ip.engine.ports.outbound.transformer_port import TransformerRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BindStreamTransformationCommand:
    """Command to configure a stream transformation to a specific transformer version."""

    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    mode: TransformationMode = TransformationMode.ACTIVE
    shadow_transformation_version: int | None = None


@dataclass(frozen=True)
class BindStreamTransformationResultDTO:
    """Result of stream transformation configuration operation."""

    id: str
    connection_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    mode: str
    shadow_transformation_version: int | None = None


class BindStreamTransformationUseCase:
    """Use case configuring or updating stream transformations in Control Plane."""

    def __init__(
        self,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        transformer_registry: TransformerRegistryPort | None = None,
    ) -> None:
        self._uow = control_plane_uow
        self._transformer_registry = transformer_registry

    async def execute(
        self, command: BindStreamTransformationCommand
    ) -> Result[BindStreamTransformationResultDTO, IpError]:
        """Execute stream transformation upsert and emit audit domain event."""
        bound_logger = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            transformation_id=command.transformation_id,
            transformation_version=command.transformation_version,
        )

        if self._transformer_registry is not None:
            if (
                self._transformer_registry.get(
                    command.transformation_id, command.transformation_version
                )
                is None
            ):
                bound_logger.error(
                    "bind_stream_transformation_version_not_registered",
                    transformation_id=command.transformation_id,
                    transformation_version=command.transformation_version,
                )
                return Result.err(
                    NormalizationFailedError.with_message(
                        f"Transformer '{command.transformation_id}' version {command.transformation_version} is not registered."
                    )
                )
            if (
                command.shadow_transformation_version is not None
                and self._transformer_registry.get(
                    command.transformation_id, command.shadow_transformation_version
                )
                is None
            ):
                bound_logger.error(
                    "bind_stream_shadow_transformation_version_not_registered",
                    transformation_id=command.transformation_id,
                    shadow_transformation_version=command.shadow_transformation_version,
                )
                return Result.err(
                    NormalizationFailedError.with_message(
                        f"Shadow transformer '{command.transformation_id}' version {command.shadow_transformation_version} is not registered."
                    )
                )

        existing = await self._uow.transformations.get_by_stream(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
        )

        if existing is None:
            transformation = Transformation.create(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream,
                transformation_id=command.transformation_id,
                transformation_version=command.transformation_version,
                mode=command.mode,
                shadow_transformation_version=command.shadow_transformation_version,
            )
        else:
            transformation = Transformation(
                id=existing.id,
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream,
                transformation_id=command.transformation_id,
                transformation_version=command.transformation_version,
                mode=command.mode,
                shadow_transformation_version=command.shadow_transformation_version,
                created_at=existing.created_at,
                updated_at=datetime.now(UTC),
            )

        transformation.add_domain_event(
            TransformationChangedEvent(
                id=transformation.id,
                tenant_id=transformation.tenant_id,
                connection_id=transformation.connection_id,
                stream=transformation.stream,
                transformation_id=transformation.transformation_id,
                transformation_version=transformation.transformation_version,
                mode=transformation.mode.value,
                shadow_transformation_version=transformation.shadow_transformation_version,
            )
        )

        await self._uow.transformations.save(transformation)
        await self._uow.commit()

        bound_logger.info("stream_transformation_bound", id=transformation.id)

        return Result.ok(
            BindStreamTransformationResultDTO(
                id=transformation.id,
                connection_id=transformation.connection_id,
                stream=transformation.stream,
                transformation_id=transformation.transformation_id,
                transformation_version=transformation.transformation_version,
                mode=transformation.mode.value,
                shadow_transformation_version=transformation.shadow_transformation_version,
            )
        )
