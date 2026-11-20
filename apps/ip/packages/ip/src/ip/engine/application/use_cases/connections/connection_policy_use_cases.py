"""Application use cases for managing operational Connection Policies (Full CRUD)."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from seedwork.domain.types import JsonDict

from ip.engine.domain.connection.connection_policy import ConnectionPolicy
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    ConnectionPolicyNotFoundError,
    IpError,
    Result,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ConnectionPolicyDTO:
    """Strongly-typed DTO mapping ip.connection_policies table."""

    id: str
    tenant_id: str
    connection_id: str
    max_query_window_days: int = 1
    max_query_window_hours: int | None = None
    min_query_window_minutes: int = 15
    max_entities_per_call: int = 100
    max_records_per_batch: int = 10000
    max_concurrency: int = 2
    rate_limit_rpm: int = 60
    cooldown_seconds_between_calls: float = 0.0
    supports_wildcard_queries: bool = False
    blackout_cron_schedule: str | None = None
    blackout_duration_minutes: int = 0
    vendor_quirks: JsonDict = field(default_factory=dict)
    is_enabled: bool = True
    created_at: str
    updated_at: str


@dataclass(frozen=True, kw_only=True)
class GetConnectionPolicyQuery:
    """Query to retrieve operational policy for a specific connection."""

    tenant_id: str
    connection_id: str


@dataclass(frozen=True, kw_only=True)
class UpsertConnectionPolicyCommand:
    """Command to create or update operational policy for a connection."""

    tenant_id: str
    connection_id: str
    policy_id: str | None = None
    max_query_window_days: int | None = None
    max_query_window_hours: int | None = None
    min_query_window_minutes: int | None = None
    max_entities_per_call: int | None = None
    max_records_per_batch: int | None = None
    max_concurrency: int | None = None
    rate_limit_rpm: int | None = None
    cooldown_seconds_between_calls: float | None = None
    supports_wildcard_queries: bool | None = None
    blackout_cron_schedule: str | None = None
    blackout_duration_minutes: int | None = None
    vendor_quirks: JsonDict | None = None
    is_enabled: bool | None = None


@dataclass(frozen=True, kw_only=True)
class DeleteConnectionPolicyCommand:
    """Command to delete operational policy for a connection."""

    tenant_id: str
    connection_id: str


def _to_policy_dto(policy: ConnectionPolicy) -> ConnectionPolicyDTO:
    return ConnectionPolicyDTO(
        id=policy.id,
        tenant_id=policy.tenant_id,
        connection_id=policy.connection_id,
        max_query_window_days=policy.max_query_window_days,
        max_query_window_hours=policy.max_query_window_hours,
        min_query_window_minutes=policy.min_query_window_minutes,
        max_entities_per_call=policy.max_entities_per_call,
        max_records_per_batch=policy.max_records_per_batch,
        max_concurrency=policy.max_concurrency,
        rate_limit_rpm=policy.rate_limit_rpm,
        cooldown_seconds_between_calls=policy.cooldown_seconds_between_calls,
        supports_wildcard_queries=policy.supports_wildcard_queries,
        blackout_cron_schedule=policy.blackout_cron_schedule,
        blackout_duration_minutes=policy.blackout_duration_minutes,
        vendor_quirks=dict(policy.vendor_quirks),
        is_enabled=policy.is_enabled,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


class GetConnectionPolicyUseCase:
    """Use case to retrieve operational policies for a specific Connection."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, query: GetConnectionPolicyQuery
    ) -> Result[ConnectionPolicyDTO, IpError]:
        bound = logger.bind(tenant_id=query.tenant_id, connection_id=query.connection_id)
        bound.info("get_connection_policy.received")

        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(query.connection_id)
            if conn is None or conn.tenant_id != query.tenant_id:
                bound.error("get_connection_policy.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(query.connection_id))

            policy = await self._cp_uow.connection_policies.get_by_connection_id(
                tenant_id=query.tenant_id,
                connection_id=query.connection_id,
            )
            if policy is None:
                bound.info("get_connection_policy.not_configured")
                return Result.err(ConnectionPolicyNotFoundError.for_connection(query.connection_id))

            bound.info("get_connection_policy.completed", policy_id=policy.id)
            return Result.ok(_to_policy_dto(policy))


class UpsertConnectionPolicyUseCase:
    """Use case to create or update operational policies for a Connection."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(
        self, command: UpsertConnectionPolicyCommand
    ) -> Result[ConnectionPolicyDTO, IpError]:
        bound = logger.bind(tenant_id=command.tenant_id, connection_id=command.connection_id)
        bound.info("upsert_connection_policy.received")

        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                bound.error("upsert_connection_policy.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

            existing = await self._cp_uow.connection_policies.get_by_connection_id(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )

            if existing is not None:
                existing.update_policy(
                    max_query_window_days=command.max_query_window_days,
                    max_query_window_hours=command.max_query_window_hours,
                    min_query_window_minutes=command.min_query_window_minutes,
                    max_entities_per_call=command.max_entities_per_call,
                    max_records_per_batch=command.max_records_per_batch,
                    max_concurrency=command.max_concurrency,
                    rate_limit_rpm=command.rate_limit_rpm,
                    cooldown_seconds_between_calls=command.cooldown_seconds_between_calls,
                    supports_wildcard_queries=command.supports_wildcard_queries,
                    blackout_cron_schedule=command.blackout_cron_schedule,
                    blackout_duration_minutes=command.blackout_duration_minutes,
                    vendor_quirks=command.vendor_quirks,
                    is_enabled=command.is_enabled,
                )
                target_policy = existing
                bound.info("upsert_connection_policy.updated", policy_id=target_policy.id)
            else:
                target_policy = ConnectionPolicy.create(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    policy_id=command.policy_id,
                    max_query_window_days=command.max_query_window_days or 1,
                    max_query_window_hours=command.max_query_window_hours,
                    min_query_window_minutes=command.min_query_window_minutes or 15,
                    max_entities_per_call=command.max_entities_per_call or 100,
                    max_records_per_batch=command.max_records_per_batch or 10000,
                    max_concurrency=command.max_concurrency or 2,
                    rate_limit_rpm=command.rate_limit_rpm or 60,
                    cooldown_seconds_between_calls=command.cooldown_seconds_between_calls or 0.0,
                    supports_wildcard_queries=bool(command.supports_wildcard_queries),
                    blackout_cron_schedule=command.blackout_cron_schedule,
                    blackout_duration_minutes=command.blackout_duration_minutes or 0,
                    vendor_quirks=command.vendor_quirks,
                    is_enabled=command.is_enabled if command.is_enabled is not None else True,
                )
                bound.info("upsert_connection_policy.created", policy_id=target_policy.id)

            await self._cp_uow.connection_policies.save(target_policy)
            await self._cp_uow.commit()

            return Result.ok(_to_policy_dto(target_policy))


class DeleteConnectionPolicyUseCase:
    """Use case to delete operational policies for a Connection."""

    def __init__(self, *, control_plane_uow: IpControlPlaneUnitOfWorkPort) -> None:
        self._cp_uow = control_plane_uow

    async def execute(self, command: DeleteConnectionPolicyCommand) -> Result[None, IpError]:
        bound = logger.bind(tenant_id=command.tenant_id, connection_id=command.connection_id)
        bound.info("delete_connection_policy.received")

        async with self._cp_uow:
            conn = await self._cp_uow.connections.get_by_id(command.connection_id)
            if conn is None or conn.tenant_id != command.tenant_id:
                bound.error("delete_connection_policy.connection_not_found")
                return Result.err(ConnectionNotFoundError.for_id(command.connection_id))

            existing = await self._cp_uow.connection_policies.get_by_connection_id(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
            )
            if existing is None:
                bound.error("delete_connection_policy.not_found")
                return Result.err(
                    ConnectionPolicyNotFoundError.for_connection(command.connection_id)
                )

            existing.mark_deleted()
            deleted = await self._cp_uow.connection_policies.delete(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                policy=existing,
            )
            if not deleted:
                bound.error("delete_connection_policy.failed_to_delete")
                return Result.err(
                    ConnectionPolicyNotFoundError.for_connection(command.connection_id)
                )

            await self._cp_uow.commit()
            bound.info("delete_connection_policy.completed", policy_id=existing.id)
            return Result.ok(None)


__all__ = [
    "ConnectionPolicyDTO",
    "DeleteConnectionPolicyCommand",
    "DeleteConnectionPolicyUseCase",
    "GetConnectionPolicyQuery",
    "GetConnectionPolicyUseCase",
    "UpsertConnectionPolicyCommand",
    "UpsertConnectionPolicyUseCase",
]
