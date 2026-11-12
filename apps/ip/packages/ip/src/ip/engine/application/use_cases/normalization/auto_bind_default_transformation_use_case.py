"""Subscriber use case binding connector-recommended default L3 transformations when an entity is subscribed."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.application.use_cases.connections.discover_catalog_use_case import (
    DiscoverCatalogExecutorPort,
)
from ip.engine.application.use_cases.normalization.bind_stream_transformation_use_case import (
    BindStreamTransformationCommand,
    BindStreamTransformationUseCase,
)
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import IpError, Result, TransformerNotFoundError
from ip.engine.domain.normalization.enums import TransformationMode
from ip.engine.ports.outbound.transformer_port import TransformerRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AutoBindDefaultTransformationCommand:
    """Command triggered by `ip.connection_entity.subscribed` to auto-bind default L3 transformations."""

    tenant_id: str
    connection_id: str
    stream_name: str


@dataclass(frozen=True)
class AutoBindDefaultTransformationResultDTO:
    """Outcome of checking and binding a connector-recommended default stream transformation."""

    bound: bool
    transformation_id: str | None = None
    transformation_version: int | None = None


class AutoBindDefaultTransformationOnEntitySubscribedUseCase:
    """Validates and binds a connector's default stream transformation in its own Transformation aggregate transaction."""

    def __init__(
        self,
        *,
        control_plane_uow: IpControlPlaneUnitOfWorkPort,
        discover_catalog_use_case: DiscoverCatalogExecutorPort,
        transformer_registry: TransformerRegistryPort,
    ) -> None:
        self._cp_uow = control_plane_uow
        self._discover_catalog = discover_catalog_use_case
        self._transformer_registry = transformer_registry

    async def execute(
        self, command: AutoBindDefaultTransformationCommand
    ) -> Result[AutoBindDefaultTransformationResultDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream_name,
        )
        bound.info("auto_bind_default_transformation.received")

        async with self._cp_uow:
            existing = await self._cp_uow.transformations.get_by_stream(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream=command.stream_name,
            )
            if existing is not None:
                bound.info(
                    "auto_bind_default_transformation.already_bound",
                    transformation_id=existing.transformation_id,
                    transformation_version=existing.transformation_version,
                )
                return Result.ok(
                    AutoBindDefaultTransformationResultDTO(
                        bound=False,
                        transformation_id=existing.transformation_id,
                        transformation_version=existing.transformation_version,
                    )
                )

        discover_res = await self._discover_catalog.execute(
            connection_id=command.connection_id,
            tenant_id=command.tenant_id,
        )
        if discover_res.is_err or discover_res.value is None:
            err = discover_res.unwrap_err()
            if err.disposition == FailureDisposition.RETRY:
                bound.error(
                    "auto_bind_default_transformation.discovery_retryable_failure",
                    error_code=err.code.value,
                )
                return Result.err(err)
            bound.info(
                "auto_bind_default_transformation.discovery_skipped",
                reason=err.code.value,
            )
            return Result.ok(AutoBindDefaultTransformationResultDTO(bound=False))

        catalog = discover_res.value
        matched_stream = next(
            (s for s in catalog.streams if s.name == command.stream_name),
            None,
        )
        if matched_stream is None or not matched_stream.default_transformation_id:
            bound.info("auto_bind_default_transformation.no_default_configured")
            return Result.ok(AutoBindDefaultTransformationResultDTO(bound=False))

        transformation_id = matched_stream.default_transformation_id
        transformation_version = matched_stream.default_transformation_version

        if self._transformer_registry.get(transformation_id, transformation_version) is None:
            not_found_err = TransformerNotFoundError.for_version(
                transformation_id,
                transformation_version,
            )
            bound.error(
                "auto_bind_default_transformation.transformer_not_registered",
                transformation_id=transformation_id,
                transformation_version=transformation_version,
                error_code=not_found_err.code.value,
            )
            return Result.err(not_found_err)

        async with self._cp_uow:
            bind_uc = BindStreamTransformationUseCase(
                control_plane_uow=self._cp_uow,
                transformer_registry=self._transformer_registry,
            )
            bind_res = await bind_uc.execute(
                BindStreamTransformationCommand(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream=command.stream_name,
                    transformation_id=transformation_id,
                    transformation_version=transformation_version,
                    mode=TransformationMode.ACTIVE,
                )
            )
            if bind_res.is_err:
                return Result.err(bind_res.unwrap_err())

        bound.info(
            "auto_bind_default_transformation.completed",
            transformation_id=transformation_id,
            transformation_version=transformation_version,
        )
        return Result.ok(
            AutoBindDefaultTransformationResultDTO(
                bound=True,
                transformation_id=transformation_id,
                transformation_version=transformation_version,
            )
        )


__all__ = [
    "AutoBindDefaultTransformationCommand",
    "AutoBindDefaultTransformationOnEntitySubscribedUseCase",
    "AutoBindDefaultTransformationResultDTO",
]
