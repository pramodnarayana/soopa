"""Application use cases for listing Layer 1, Layer 2, Layer 3, and GEM records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.domain.normalization.normalized_record import GlobalEntityMap, NormalizedRecord
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.replica_record import ReplicaRecord
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ListNormalizedRecordsQuery:
    tenant_id: str
    connection_id: str | None = None
    canonical_type: str | None = None
    limit: int = 50
    offset: int = 0


class ListNormalizedRecordsUseCase:
    """Use case to list Layer 3 Normalized canonical records."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    async def execute(
        self, query: ListNormalizedRecordsQuery
    ) -> Result[Sequence[NormalizedRecord], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
            canonical_type=query.canonical_type,
            limit=query.limit,
            offset=query.offset,
        )
        bound.info("ip_list_normalized_records.started")
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_list_normalized_records.shard_resolution_failed",
                error_code=str(err.code),
            )
            return Result.err(err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            records = await uow.normalized_records.list_records(
                query.tenant_id,
                connection_id=query.connection_id,
                canonical_type=query.canonical_type,
                limit=query.limit,
                offset=query.offset,
            )
        bound.info("ip_list_normalized_records.completed", record_count=len(records))
        return Result.ok(records)


@dataclass(frozen=True, kw_only=True)
class ListGlobalEntityMapQuery:
    tenant_id: str
    entity_domain: str | None = None
    source_connection_id: str | None = None
    limit: int = 50
    offset: int = 0


class ListGlobalEntityMapUseCase:
    """Use case to list Global Entity Map (GEM) crosswalk entries."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    async def execute(
        self, query: ListGlobalEntityMapQuery
    ) -> Result[Sequence[GlobalEntityMap], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            entity_domain=query.entity_domain,
            source_connection_id=query.source_connection_id,
            limit=query.limit,
            offset=query.offset,
        )
        bound.info("ip_list_global_entity_map.started")
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_list_global_entity_map.shard_resolution_failed",
                error_code=str(err.code),
            )
            return Result.err(err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            entries = await uow.entity_maps.list_entries(
                query.tenant_id,
                entity_domain=query.entity_domain,
                source_connection_id=query.source_connection_id,
                limit=query.limit,
                offset=query.offset,
            )
        bound.info("ip_list_global_entity_map.completed", entry_count=len(entries))
        return Result.ok(entries)


@dataclass(frozen=True, kw_only=True)
class ListReplicaRecordsQuery:
    tenant_id: str
    connection_id: str | None = None
    stream: str | None = None
    limit: int = 50
    offset: int = 0


class ListReplicaRecordsUseCase:
    """Use case to list Layer 2 Universal Replica records (restricted to Customer Support)."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    async def execute(
        self, query: ListReplicaRecordsQuery
    ) -> Result[Sequence[ReplicaRecord], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
            stream=query.stream,
            limit=query.limit,
            offset=query.offset,
        )
        bound.info("ip_list_replica_records.started")
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_list_replica_records.shard_resolution_failed",
                error_code=str(err.code),
            )
            return Result.err(err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            records = await uow.replica_records.list_records(
                query.tenant_id,
                connection_id=query.connection_id,
                stream=query.stream,
                limit=query.limit,
                offset=query.offset,
            )
        bound.info("ip_list_replica_records.completed", record_count=len(records))
        return Result.ok(records)


@dataclass(frozen=True, kw_only=True)
class ListInboundRecordsQuery:
    tenant_id: str
    connection_id: str | None = None
    stream_name: str | None = None
    limit: int = 50
    offset: int = 0
    hydrate_payloads: bool = False


class ListInboundRecordsUseCase:
    """Use case to list Layer 1 Inbound Wire records (restricted to Customer Support)."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    async def execute(
        self, query: ListInboundRecordsQuery
    ) -> Result[Sequence[InboundRecord], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
            stream_name=query.stream_name,
            limit=query.limit,
            offset=query.offset,
        )
        bound.info("ip_list_inbound_records.started")
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_list_inbound_records.shard_resolution_failed",
                error_code=str(err.code),
            )
            return Result.err(err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            records = await uow.inbound_records.list_records(
                query.tenant_id,
                connection_id=query.connection_id,
                stream_name=query.stream_name,
                limit=query.limit,
                offset=query.offset,
                hydrate_payloads=query.hydrate_payloads,
            )
        bound.info("ip_list_inbound_records.completed", record_count=len(records))
        return Result.ok(records)


@dataclass(frozen=True, kw_only=True)
class ListOutboundRecordsQuery:
    tenant_id: str
    connection_id: str | None = None
    app_id: str | None = None
    stream_name: str | None = None
    status: str | None = None
    limit: int = 50
    offset: int = 0
    hydrate_payloads: bool = False


class ListOutboundRecordsUseCase:
    """Use case to list Layer 5 Outbound delivery records."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    async def execute(
        self, query: ListOutboundRecordsQuery
    ) -> Result[Sequence[OutboundRecord], IpError]:
        bound = logger.bind(
            tenant_id=query.tenant_id,
            connection_id=query.connection_id,
            app_id=query.app_id,
            stream_name=query.stream_name,
            status=query.status,
            limit=query.limit,
            offset=query.offset,
        )
        bound.info("ip_list_outbound_records.started")
        shard_res = await self._uow_provider.resolve_shard_info(query.tenant_id)
        if shard_res.is_err:
            err = shard_res.unwrap_err()
            bound.error(
                "ip_list_outbound_records.shard_resolution_failed",
                error_code=str(err.code),
            )
            return Result.err(err)

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            query.tenant_id, shard_id, shard_dsn
        ) as uow:
            records = await uow.outbound_records.list_records(
                query.tenant_id,
                connection_id=query.connection_id,
                app_id=query.app_id,
                stream_name=query.stream_name,
                status=query.status,
                limit=query.limit,
                offset=query.offset,
                hydrate_payloads=query.hydrate_payloads,
            )
        bound.info("ip_list_outbound_records.completed", record_count=len(records))
        return Result.ok(records)


__all__ = [
    "ListGlobalEntityMapQuery",
    "ListGlobalEntityMapUseCase",
    "ListInboundRecordsQuery",
    "ListInboundRecordsUseCase",
    "ListNormalizedRecordsQuery",
    "ListNormalizedRecordsUseCase",
    "ListOutboundRecordsQuery",
    "ListOutboundRecordsUseCase",
    "ListReplicaRecordsQuery",
    "ListReplicaRecordsUseCase",
]
