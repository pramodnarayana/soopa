"""PromoteTransformationVersionUseCase: Promotes candidate shadow transformer version to active."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from ip.engine.domain.enums import TransformationMode
from ip.engine.domain.events import TransformationVersionPromotedEvent
from ip.engine.domain.exceptions import (
    IpError,
    NormalizationFailedError,
    Result,
    TransformationNotFoundError,
)
from ip.engine.domain.normalization import Transformation
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PromoteTransformationVersionCommand:
    """Command to promote shadow transformer version to active."""

    tenant_id: str
    connection_id: str
    stream: str


@dataclass(frozen=True)
class PromoteTransformationVersionResultDTO:
    """Result of transformation version promotion."""

    id: str
    connection_id: str
    stream: str
    transformation_id: str
    promoted_version: int
    previous_version: int


class PromoteTransformationVersionUseCase:
    """Use case promoting a candidate shadow transformation version to active production status."""

    def __init__(self, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._uow = control_plane_uow

    async def execute(
        self, command: PromoteTransformationVersionCommand
    ) -> Result[PromoteTransformationVersionResultDTO, IpError]:
        """Promote shadow version to active, clearing shadow version and emitting event."""
        bound_logger = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
        )

        transformation = await self._uow.transformations.get_by_stream(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
        )
        if transformation is None:
            return Result.err(
                TransformationNotFoundError.for_stream(
                    connection_id=command.connection_id,
                    stream=command.stream,
                )
            )

        if transformation.shadow_transformation_version is None:
            return Result.err(
                NormalizationFailedError.with_message(
                    f"No candidate shadow_transformation_version configured on transformation '{transformation.id}' to promote."
                )
            )

        previous_version = transformation.transformation_version
        promoted_version = transformation.shadow_transformation_version

        updated_transformation = Transformation(
            id=transformation.id,
            tenant_id=transformation.tenant_id,
            connection_id=transformation.connection_id,
            stream=transformation.stream,
            transformation_id=transformation.transformation_id,
            transformation_version=promoted_version,
            mode=TransformationMode.ACTIVE,
            shadow_transformation_version=None,
            created_at=transformation.created_at,
            updated_at=datetime.now(UTC),
        )

        updated_transformation.add_domain_event(
            TransformationVersionPromotedEvent(
                id=updated_transformation.id,
                tenant_id=updated_transformation.tenant_id,
                connection_id=updated_transformation.connection_id,
                stream=updated_transformation.stream,
                transformation_id=updated_transformation.transformation_id,
                promoted_version=promoted_version,
                previous_version=previous_version,
            )
        )

        await self._uow.transformations.save(updated_transformation)
        await self._uow.commit()

        bound_logger.info(
            "transformation_version_promoted",
            id=updated_transformation.id,
            previous_version=previous_version,
            promoted_version=promoted_version,
        )

        return Result.ok(
            PromoteTransformationVersionResultDTO(
                id=updated_transformation.id,
                connection_id=updated_transformation.connection_id,
                stream=updated_transformation.stream,
                transformation_id=updated_transformation.transformation_id,
                promoted_version=promoted_version,
                previous_version=previous_version,
            )
        )
