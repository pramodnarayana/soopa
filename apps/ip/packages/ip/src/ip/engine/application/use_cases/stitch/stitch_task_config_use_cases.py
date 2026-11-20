"""Application use cases for managing Stitch DAG Task Runtime Configurations."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.domain.exceptions import (
    IpError,
    Result,
    StitchNotFoundError,
    StitchTaskConfigNotFoundError,
)
from ip.engine.domain.stitch.stitch_task_config import StitchTaskConfig
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class StitchTaskConfigDTO:
    """Strongly-typed DTO mapping ip.stitch_task_configs table."""

    id: str
    tenant_id: str
    stitch_id: str
    node_key: str
    timeout_seconds: int = 60
    heartbeat_interval_seconds: int = 15
    max_attempts: int = 5
    initial_delay_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 60.0
    queue_name: str = "default"
    max_in_flight_tasks: int = 3
    failure_disposition: str = "RETRY_THEN_QUARANTINE"
    quarantine_stream_name: str | None = "dead_letter_records"
    created_at: str
    updated_at: str


@dataclass(frozen=True, kw_only=True)
class GetStitchTaskConfigQuery:
    """Query to retrieve runtime execution policy for a specific stitch DAG node."""

    tenant_id: str
    stitch_id: str
    node_key: str


@dataclass(frozen=True, kw_only=True)
class ListStitchTaskConfigsQuery:
    """Query to list all node runtime configurations for a stitch."""

    tenant_id: str
    stitch_id: str


@dataclass(frozen=True, kw_only=True)
class UpsertStitchTaskConfigCommand:
    """Command to create or update runtime execution policy for a stitch DAG node."""

    tenant_id: str
    stitch_id: str
    node_key: str
    config_id: str | None = None
    timeout_seconds: int | None = None
    heartbeat_interval_seconds: int | None = None
    max_attempts: int | None = None
    initial_delay_seconds: float | None = None
    backoff_multiplier: float | None = None
    max_delay_seconds: float | None = None
    queue_name: str | None = None
    max_in_flight_tasks: int | None = None
    failure_disposition: str | None = None
    quarantine_stream_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class DeleteStitchTaskConfigCommand:
    """Command to delete runtime execution policy for a stitch DAG node."""

    tenant_id: str
    stitch_id: str
    node_key: str


def _to_task_config_dto(cfg: StitchTaskConfig) -> StitchTaskConfigDTO:
    return StitchTaskConfigDTO(
        id=cfg.id,
        tenant_id=cfg.tenant_id,
        stitch_id=cfg.stitch_id,
        node_key=cfg.node_key,
        timeout_seconds=cfg.timeout_seconds,
        heartbeat_interval_seconds=cfg.heartbeat_interval_seconds,
        max_attempts=cfg.max_attempts,
        initial_delay_seconds=cfg.initial_delay_seconds,
        backoff_multiplier=cfg.backoff_multiplier,
        max_delay_seconds=cfg.max_delay_seconds,
        queue_name=cfg.queue_name,
        max_in_flight_tasks=cfg.max_in_flight_tasks,
        failure_disposition=cfg.failure_disposition,
        quarantine_stream_name=cfg.quarantine_stream_name,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


class GetStitchTaskConfigUseCase:
    """Use case to retrieve runtime execution policy for a specific stitch DAG node."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, query: GetStitchTaskConfigQuery
    ) -> Result[StitchTaskConfigDTO, IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            stitch_id=query.stitch_id,
            node_key=query.node_key,
        )
        bound.info("get_stitch_task_config.received")

        async with self._cp_uow:
            stitch = await self._cp_uow.stitches.get_by_id(
                tenant_id=query.tenant_id,
                stitch_id=query.stitch_id,
            )
            if stitch is None:
                bound.error("get_stitch_task_config.stitch_not_found")
                return Result.err(StitchNotFoundError.for_id(query.stitch_id))

            cfg = await self._cp_uow.stitch_task_configs.get_by_node(
                tenant_id=query.tenant_id,
                stitch_id=query.stitch_id,
                node_key=query.node_key,
            )
            if cfg is None:
                bound.info("get_stitch_task_config.not_found")
                return Result.err(
                    StitchTaskConfigNotFoundError.for_node(query.stitch_id, query.node_key)
                )

            bound.info("get_stitch_task_config.completed", config_id=cfg.id)
            return Result.ok(_to_task_config_dto(cfg))


class ListStitchTaskConfigsUseCase:
    """Use case to list all task runtime execution policies for a stitch."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, query: ListStitchTaskConfigsQuery
    ) -> Result[tuple[StitchTaskConfigDTO, ...], IpError]:
        bound = logger.bind(tenant_id=query.tenant_id, stitch_id=query.stitch_id)
        bound.info("list_stitch_task_configs.received")

        async with self._cp_uow:
            stitch = await self._cp_uow.stitches.get_by_id(
                tenant_id=query.tenant_id,
                stitch_id=query.stitch_id,
            )
            if stitch is None:
                bound.error("list_stitch_task_configs.stitch_not_found")
                return Result.err(StitchNotFoundError.for_id(query.stitch_id))

            configs = await self._cp_uow.stitch_task_configs.list_by_stitch(
                tenant_id=query.tenant_id,
                stitch_id=query.stitch_id,
            )
            dtos = tuple(_to_task_config_dto(c) for c in configs)
            bound.info("list_stitch_task_configs.completed", count=len(dtos))
            return Result.ok(dtos)


class UpsertStitchTaskConfigUseCase:
    """Use case to create or update runtime execution policy for a stitch DAG node."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, command: UpsertStitchTaskConfigCommand
    ) -> Result[StitchTaskConfigDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            stitch_id=command.stitch_id,
            node_key=command.node_key,
        )
        bound.info("upsert_stitch_task_config.received")

        async with self._cp_uow:
            stitch = await self._cp_uow.stitches.get_by_id(
                tenant_id=command.tenant_id,
                stitch_id=command.stitch_id,
            )
            if stitch is None:
                bound.error("upsert_stitch_task_config.stitch_not_found")
                return Result.err(StitchNotFoundError.for_id(command.stitch_id))

            existing = await self._cp_uow.stitch_task_configs.get_by_node(
                tenant_id=command.tenant_id,
                stitch_id=command.stitch_id,
                node_key=command.node_key,
            )

            if existing is not None:
                existing.update_config(
                    timeout_seconds=command.timeout_seconds,
                    heartbeat_interval_seconds=command.heartbeat_interval_seconds,
                    max_attempts=command.max_attempts,
                    initial_delay_seconds=command.initial_delay_seconds,
                    backoff_multiplier=command.backoff_multiplier,
                    max_delay_seconds=command.max_delay_seconds,
                    queue_name=command.queue_name,
                    max_in_flight_tasks=command.max_in_flight_tasks,
                    failure_disposition=command.failure_disposition,
                    quarantine_stream_name=command.quarantine_stream_name,
                )
                target = existing
                bound.info("upsert_stitch_task_config.updated", config_id=target.id)
            else:
                target = StitchTaskConfig.create(
                    tenant_id=command.tenant_id,
                    stitch_id=command.stitch_id,
                    node_key=command.node_key,
                    config_id=command.config_id,
                    timeout_seconds=command.timeout_seconds or 60,
                    heartbeat_interval_seconds=command.heartbeat_interval_seconds or 15,
                    max_attempts=command.max_attempts or 5,
                    initial_delay_seconds=command.initial_delay_seconds or 2.0,
                    backoff_multiplier=command.backoff_multiplier or 2.0,
                    max_delay_seconds=command.max_delay_seconds or 60.0,
                    queue_name=command.queue_name or "default",
                    max_in_flight_tasks=command.max_in_flight_tasks or 3,
                    failure_disposition=command.failure_disposition or "RETRY_THEN_QUARANTINE",
                    quarantine_stream_name=command.quarantine_stream_name or "dead_letter_records",
                )
                bound.info("upsert_stitch_task_config.created", config_id=target.id)

            await self._cp_uow.stitch_task_configs.save(target)
            await self._cp_uow.commit()

            return Result.ok(_to_task_config_dto(target))


class DeleteStitchTaskConfigUseCase:
    """Use case to delete runtime execution policy for a stitch DAG node."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(self, command: DeleteStitchTaskConfigCommand) -> Result[None, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            stitch_id=command.stitch_id,
            node_key=command.node_key,
        )
        bound.info("delete_stitch_task_config.received")

        async with self._cp_uow:
            existing = await self._cp_uow.stitch_task_configs.get_by_node(
                tenant_id=command.tenant_id,
                stitch_id=command.stitch_id,
                node_key=command.node_key,
            )
            if existing is None:
                bound.error("delete_stitch_task_config.not_found")
                return Result.err(
                    StitchTaskConfigNotFoundError.for_node(command.stitch_id, command.node_key)
                )

            existing.mark_deleted()
            deleted = await self._cp_uow.stitch_task_configs.delete(
                tenant_id=command.tenant_id,
                stitch_id=command.stitch_id,
                node_key=command.node_key,
                config=existing,
            )
            if not deleted:
                bound.error("delete_stitch_task_config.failed_to_delete")
                return Result.err(
                    StitchTaskConfigNotFoundError.for_node(command.stitch_id, command.node_key)
                )

            await self._cp_uow.commit()
            bound.info("delete_stitch_task_config.completed", config_id=existing.id)
            return Result.ok(None)


__all__ = [
    "DeleteStitchTaskConfigCommand",
    "DeleteStitchTaskConfigUseCase",
    "GetStitchTaskConfigQuery",
    "GetStitchTaskConfigUseCase",
    "ListStitchTaskConfigsQuery",
    "ListStitchTaskConfigsUseCase",
    "StitchTaskConfigDTO",
    "UpsertStitchTaskConfigCommand",
    "UpsertStitchTaskConfigUseCase",
]
