"""Control Plane query use cases for inspecting registered transformers and stream transformations."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.domain.enums import TransformationMode
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    IpError,
    Result,
    TransformationNotFoundError,
)
from ip.engine.domain.normalization import Transformation
from ip.engine.ports.outbound.transformer_port import TransformerRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TransformationDTO:
    """Pure boundary DTO representing a configured stream Transformation."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    mode: TransformationMode
    shadow_transformation_version: int | None = None


@dataclass(frozen=True)
class RegisteredTransformerDTO:
    """Summary of a registered pure L3 code transformer."""

    transformation_id: str
    transformation_version: int
    target_types: tuple[str, ...]


@dataclass(frozen=True)
class ListConnectionTransformationsQuery:
    """Query to list all stream transformations configured on a connection."""

    tenant_id: str
    connection_id: str


@dataclass(frozen=True)
class GetStreamTransformationQuery:
    """Query to fetch a specific stream transformation on a connection."""

    tenant_id: str
    connection_id: str
    stream: str


def _to_transformation_dto(transformation: Transformation) -> TransformationDTO:
    return TransformationDTO(
        id=transformation.id,
        tenant_id=transformation.tenant_id,
        connection_id=transformation.connection_id,
        stream=transformation.stream,
        transformation_id=transformation.transformation_id,
        transformation_version=transformation.transformation_version,
        mode=transformation.mode,
        shadow_transformation_version=transformation.shadow_transformation_version,
    )


class ListRegisteredTransformersUseCase:
    """Returns all registered pure L3 transformers sorted by (transformation_id, transformation_version)."""

    def __init__(self, *, transformer_registry: TransformerRegistryPort) -> None:
        self._transformer_registry = transformer_registry

    def execute(self) -> tuple[RegisteredTransformerDTO, ...]:
        transformers = self._transformer_registry.list_transformers()
        dtos = [
            RegisteredTransformerDTO(
                transformation_id=t.transformation_id,
                transformation_version=t.transformation_version,
                target_types=t.target_types,
            )
            for t in transformers
        ]
        dtos.sort(key=lambda d: (d.transformation_id, d.transformation_version))
        logger.info("list_registered_transformers.completed", count=len(dtos))
        return tuple(dtos)


class ListConnectionTransformationsUseCase:
    """Lists all stream transformations configured for a connection."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, query: ListConnectionTransformationsQuery
    ) -> Result[tuple[TransformationDTO, ...], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
        )
        bound.info("list_connection_transformations.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(query.connection_id)
            if conn is None or conn.tenant_id != query.tenant_id:
                bound.error("list_connection_transformations.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(query.connection_id))

            transformations = await self._cp_uow.transformations.list_by_connection(
                tenant_id=query.tenant_id,
                connection_id=query.connection_id,
            )
            dtos = tuple(_to_transformation_dto(t) for t in transformations)
            bound.info("list_connection_transformations.completed", count=len(dtos))
            return Result.ok(dtos)


class GetStreamTransformationUseCase:
    """Retrieves the stream transformation for a specific connection stream."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, query: GetStreamTransformationQuery
    ) -> Result[TransformationDTO, IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
            stream=query.stream,
        )
        bound.info("get_stream_transformation.received")
        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(query.connection_id)
            if conn is None or conn.tenant_id != query.tenant_id:
                bound.error("get_stream_transformation.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(query.connection_id))

            transformation = await self._cp_uow.transformations.get_by_stream(
                tenant_id=query.tenant_id,
                connection_id=query.connection_id,
                stream=query.stream,
            )
            if transformation is None:
                bound.error("get_stream_transformation.not_found")
                return Result.err(
                    TransformationNotFoundError.for_stream(query.connection_id, query.stream)
                )

            bound.info("get_stream_transformation.completed", id=transformation.id)
            return Result.ok(_to_transformation_dto(transformation))


__all__ = [
    "GetStreamTransformationQuery",
    "GetStreamTransformationUseCase",
    "ListConnectionTransformationsQuery",
    "ListConnectionTransformationsUseCase",
    "ListRegisteredTransformersUseCase",
    "RegisteredTransformerDTO",
    "TransformationDTO",
]
