"""Tenant-aware adapters for OutboundRecordLookup, ReplicaLookup, and NotificationOutbox."""

from __future__ import annotations

import structlog
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.replication.replica_record import ReplicaRecord
from ip.engine.ports.outbound.notification_outbox_port import NotificationOutboxPort
from ip.engine.ports.outbound.outbound_record_lookup_port import (
    OutboundRecordLookupPort,
)
from ip.engine.ports.outbound.replica_lookup_port import ReplicaLookupPort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from seedwork.events import EventEnvelope

logger = structlog.get_logger(__name__)


class TenantAwareOutboundRecordLookupAdapter(OutboundRecordLookupPort):
    """Adapter fulfilling OutboundRecordLookupPort by routing to the tenant shard via IpDataPlaneUnitOfWorkProviderPort."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._provider = uow_provider

    async def get_by_idempotency_key(
        self,
        tenant_id: str,
        connection_id: str,
        idempotency_key: str,
    ) -> OutboundRecord | None:
        shard_info_res = await self._provider.resolve_shard_info(tenant_id)
        if shard_info_res.is_err:
            return None
        shard_id, shard_dsn = shard_info_res.unwrap()
        async with self._provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
            return await uow.outbound_records.get_by_idempotency_key(
                tenant_id=tenant_id,
                connection_id=connection_id,
                idempotency_key=idempotency_key,
            )


class TenantAwareReplicaLookupAdapter(ReplicaLookupPort):
    """Adapter fulfilling ReplicaLookupPort by querying the tenant shard via IpDataPlaneUnitOfWorkProviderPort."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._provider = uow_provider

    async def get_by_key(
        self,
        tenant_id: str,
        connection_id: str,
        stream: str,
        record_key: str,
    ) -> ReplicaRecord | None:
        shard_info_res = await self._provider.resolve_shard_info(tenant_id)
        if shard_info_res.is_err:
            err_msg = shard_info_res.unwrap_err().message
            logger.error(
                "tenant_aware_replica_lookup.shard_resolution_failed",
                tenant_id=tenant_id,
                error=err_msg,
            )
            raise RuntimeError(f"Cannot resolve physical shard for tenant '{tenant_id}': {err_msg}")
        shard_id, shard_dsn = shard_info_res.unwrap()
        async with self._provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
            return await uow.replica_records.get_by_key(
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream=stream,
                record_key=record_key,
            )


class TenantAwareNotificationOutboxAdapter(NotificationOutboxPort):
    """Adapter fulfilling NotificationOutboxPort by staging Stage-1 notification envelopes to the tenant shard outbox."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._provider = uow_provider

    async def publish_envelope(self, envelope: EventEnvelope) -> None:
        tenant_id = envelope.tenant_id
        if not tenant_id:
            raise ValueError("Cannot stage notification envelope without tenant_id.")
        shard_info_res = await self._provider.resolve_shard_info(tenant_id)
        if shard_info_res.is_err:
            err_msg = shard_info_res.unwrap_err().message
            logger.error(
                "tenant_aware_notification_outbox.shard_resolution_failed",
                tenant_id=tenant_id,
                error=err_msg,
            )
            raise RuntimeError(f"Cannot resolve physical shard for tenant '{tenant_id}': {err_msg}")
        shard_id, shard_dsn = shard_info_res.unwrap()
        async with self._provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
            await uow.stage_outbox_envelope(envelope)
            await uow.commit()


__all__ = [
    "TenantAwareNotificationOutboxAdapter",
    "TenantAwareOutboundRecordLookupAdapter",
    "TenantAwareReplicaLookupAdapter",
]
