"""PromoteTransformationVersionUseCase: Promotes candidate shadow transformer version to active."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.domain.exceptions import (
    IpError,
    Result,
    TransformationNotFoundError,
)
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

        promote_res = transformation.promote_shadow_version()
        if promote_res.is_err:
            return Result.err(promote_res.unwrap_err())

        previous_version, promoted_version = promote_res.unwrap()

        await self._uow.transformations.save(transformation)
        await self._uow.commit()

        bound_logger.info(
            "transformation_version_promoted",
            id=transformation.id,
            previous_version=previous_version,
            promoted_version=promoted_version,
        )

        return Result.ok(
            PromoteTransformationVersionResultDTO(
                id=transformation.id,
                connection_id=transformation.connection_id,
                stream=transformation.stream,
                transformation_id=transformation.transformation_id,
                promoted_version=promoted_version,
                previous_version=previous_version,
            )
        )
