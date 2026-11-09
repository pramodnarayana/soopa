"""SQLAlchemy repository adapter for BatchManifest reconciliation ledger (`ip_batch_manifests`)."""

from __future__ import annotations

from collections.abc import Sequence

from ip.engine.adapters.outbound.database.base_repository import TenantSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.data_plane import BatchManifestModel
from ip.engine.domain.intervals.enums import (
    BatchManifestStatus,
    IntervalPayloadFormat,
    PriorityLane,
)
from ip.engine.domain.intervals.models import (
    BatchManifest,
    BatchReconciliationSummary,
)
from ip.engine.ports.outbound.batch_manifest_repository_port import (
    BatchManifestRepositoryPort,
)
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyBatchManifestRepository(
    TenantSqlAlchemyRepository,
    BatchManifestRepositoryPort,
):
    """Persists and queries interval BatchManifest entities with Zero-Loss reconciliation."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(orm: BatchManifestModel) -> BatchManifest:
        """Strict type-safe Data Mapper from ORM model to Domain Aggregate."""
        return BatchManifest(
            id=orm.id,
            tenant_id=orm.tenant_id,
            trace_id=orm.trace_id,
            correlation_id=orm.correlation_id,
            parent_trace_id=orm.parent_trace_id,
            original_trace_id=orm.original_trace_id,
            replay_count=orm.replay_count,
            connection_id=orm.connection_id,
            app_id=orm.app_id,
            stream_name=orm.stream_name,
            priority_lane=PriorityLane(orm.priority_lane),
            payload_format=IntervalPayloadFormat(orm.payload_format),
            status=BatchManifestStatus(orm.status),
            l1_raw_uri=orm.l1_raw_uri,
            l2_replica_uri=orm.l2_replica_uri,
            l3_canonical_uri=orm.l3_canonical_uri,
            inline_payload=dict(orm.inline_payload) if orm.inline_payload is not None else None,
            payload_sha256=orm.payload_sha256,
            payload_size_bytes=int(orm.payload_size_bytes),
            window_start_utc=orm.window_start_utc,
            window_end_utc=orm.window_end_utc,
            raw_ingested_count=int(orm.raw_ingested_count),
            duplicates_dropped_count=int(orm.duplicates_dropped_count),
            valid_canonical_count=int(orm.valid_canonical_count),
            quarantined_held_count=int(orm.quarantined_held_count),
            promoted_outage_clusters_count=int(orm.promoted_outage_clusters_count),
            delivery_receipt_id=orm.delivery_receipt_id,
            error_message=orm.error_message,
            created_at=orm.created_at,
            completed_at=orm.completed_at,
        )

    @staticmethod
    def _to_orm_model(domain: BatchManifest) -> BatchManifestModel:
        """Strict type-safe Data Mapper from Domain Aggregate to ORM model."""
        return BatchManifestModel(
            id=domain.id,
            tenant_id=domain.tenant_id,
            trace_id=domain.trace_id,
            correlation_id=domain.correlation_id,
            parent_trace_id=domain.parent_trace_id,
            original_trace_id=domain.original_trace_id,
            replay_count=domain.replay_count,
            connection_id=domain.connection_id,
            app_id=domain.app_id,
            stream_name=domain.stream_name,
            priority_lane=domain.priority_lane.value,
            payload_format=domain.payload_format.value,
            status=domain.status.value,
            l1_raw_uri=domain.l1_raw_uri,
            l2_replica_uri=domain.l2_replica_uri,
            l3_canonical_uri=domain.l3_canonical_uri,
            inline_payload=domain.inline_payload,
            payload_sha256=domain.payload_sha256,
            payload_size_bytes=domain.payload_size_bytes,
            window_start_utc=domain.window_start_utc,
            window_end_utc=domain.window_end_utc,
            raw_ingested_count=domain.raw_ingested_count,
            duplicates_dropped_count=domain.duplicates_dropped_count,
            valid_canonical_count=domain.valid_canonical_count,
            quarantined_held_count=domain.quarantined_held_count,
            promoted_outage_clusters_count=domain.promoted_outage_clusters_count,
            delivery_receipt_id=domain.delivery_receipt_id,
            error_message=domain.error_message,
            created_at=domain.created_at,
            completed_at=domain.completed_at,
        )

    @staticmethod
    def _update_orm_from_domain(orm: BatchManifestModel, domain: BatchManifest) -> None:
        """Updates an existing ORM instance from the Domain Aggregate via explicit dot notation."""
        orm.status = domain.status.value
        orm.priority_lane = domain.priority_lane.value
        orm.payload_format = domain.payload_format.value
        orm.l1_raw_uri = domain.l1_raw_uri
        orm.l2_replica_uri = domain.l2_replica_uri
        orm.l3_canonical_uri = domain.l3_canonical_uri
        orm.inline_payload = domain.inline_payload
        orm.raw_ingested_count = domain.raw_ingested_count
        orm.duplicates_dropped_count = domain.duplicates_dropped_count
        orm.valid_canonical_count = domain.valid_canonical_count
        orm.quarantined_held_count = domain.quarantined_held_count
        orm.promoted_outage_clusters_count = domain.promoted_outage_clusters_count
        orm.delivery_receipt_id = domain.delivery_receipt_id
        orm.error_message = domain.error_message
        orm.completed_at = domain.completed_at

    async def save(self, manifest: BatchManifest) -> None:
        stmt = select(BatchManifestModel).where(
            BatchManifestModel.id == manifest.id,
            BatchManifestModel.tenant_id == manifest.tenant_id,
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            self._session.add(self._to_orm_model(manifest))
        else:
            self._update_orm_from_domain(existing, manifest)

        self._drain_trace_events(manifest)
        self._drain_events(manifest, default_tenant_id=manifest.tenant_id)
        await self._session.flush()

    async def get_by_id(self, batch_id: str, tenant_id: str) -> BatchManifest | None:
        stmt = select(BatchManifestModel).where(
            BatchManifestModel.id == batch_id,
            BatchManifestModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def get_by_sha256(
        self,
        tenant_id: str,
        connection_id: str,
        payload_sha256: str,
    ) -> BatchManifest | None:
        stmt = select(BatchManifestModel).where(
            BatchManifestModel.tenant_id == tenant_id,
            BatchManifestModel.connection_id == connection_id,
            BatchManifestModel.payload_sha256 == payload_sha256,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def list_by_connection(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[BatchManifest]:
        stmt = select(BatchManifestModel).where(BatchManifestModel.tenant_id == tenant_id)
        if connection_id is not None:
            stmt = stmt.where(BatchManifestModel.connection_id == connection_id)
        stmt = stmt.order_by(
            BatchManifestModel.created_at.desc(),
            BatchManifestModel.id.desc(),
        ).limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_domain_model(orm) for orm in result.scalars().all()]

    async def get_reconciliation_summary(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
    ) -> BatchReconciliationSummary:
        completed_cond = BatchManifestModel.status == BatchManifestStatus.COMPLETED.value
        in_flight_cond = BatchManifestModel.status.in_(
            (BatchManifestStatus.INGESTED.value, BatchManifestStatus.PROCESSING.value)
        )
        failed_cond = BatchManifestModel.status == BatchManifestStatus.FAILED.value

        stmt = select(
            func.count(BatchManifestModel.id),
            func.coalesce(func.sum(case((completed_cond, 1), else_=0)), 0),
            func.coalesce(func.sum(case((in_flight_cond, 1), else_=0)), 0),
            func.coalesce(func.sum(case((failed_cond, 1), else_=0)), 0),
            func.coalesce(func.sum(BatchManifestModel.raw_ingested_count), 0),
            func.coalesce(func.sum(BatchManifestModel.duplicates_dropped_count), 0),
            func.coalesce(func.sum(BatchManifestModel.valid_canonical_count), 0),
            func.coalesce(func.sum(BatchManifestModel.quarantined_held_count), 0),
            func.coalesce(
                func.sum(
                    case(
                        (in_flight_cond, BatchManifestModel.raw_ingested_count),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(BatchManifestModel.tenant_id == tenant_id)

        if connection_id is not None:
            stmt = stmt.where(BatchManifestModel.connection_id == connection_id)

        result = await self._session.execute(stmt)
        row = result.one()
        total_batches = int(row[0] or 0)
        completed_batches = int(row[1] or 0)
        in_flight_batches = int(row[2] or 0)
        failed_batches = int(row[3] or 0)
        raw_ingested_total = int(row[4] or 0)
        duplicates_dropped_total = int(row[5] or 0)
        valid_canonical_total = int(row[6] or 0)
        quarantined_held_total = int(row[7] or 0)
        in_flight_readings_total = int(row[8] or 0)

        accounted_plus_inflight = (
            duplicates_dropped_total
            + valid_canonical_total
            + quarantined_held_total
            + in_flight_readings_total
        )
        is_balanced = failed_batches == 0 and raw_ingested_total == accounted_plus_inflight

        return BatchReconciliationSummary(
            tenant_id=tenant_id,
            connection_id=connection_id,
            total_batches=total_batches,
            completed_batches=completed_batches,
            in_flight_batches=in_flight_batches,
            failed_batches=failed_batches,
            raw_ingested_total=raw_ingested_total,
            duplicates_dropped_total=duplicates_dropped_total,
            valid_canonical_total=valid_canonical_total,
            quarantined_held_total=quarantined_held_total,
            in_flight_readings_total=in_flight_readings_total,
            is_zero_loss_balanced=is_balanced,
        )


__all__ = ["SqlAlchemyBatchManifestRepository"]
