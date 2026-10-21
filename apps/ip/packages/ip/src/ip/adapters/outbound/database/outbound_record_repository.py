"""SQLAlchemy adapter for Layer 5 OutboundRecord repository."""

from __future__ import annotations

from collections.abc import Sequence

from ip.adapters.outbound.database.models.outbound_record_model import OutboundRecordModel
from ip.adapters.outbound.database.models.outbox_model import IpOutboxRecord
from ip.domain.enums import OutboundDispatchStatus
from ip.domain.models.outbound_record import OutboundRecord
from ip.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from outbox.domain.constants import OutboxStatus
from seedwork.utils import generate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.outbox_serializer import serialize_domain_event


class SqlAlchemyOutboundRecordRepository(OutboundRecordRepositoryPort):
    """Repository persisting and retrieving OutboundRecord audit entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain_model(orm: OutboundRecordModel) -> OutboundRecord:
        """Strict type-safe Data Mapper from ORM model to Domain Aggregate."""
        return OutboundRecord(
            id=orm.id,
            tenant_id=orm.tenant_id,
            connection_id=orm.connection_id,
            app_id=orm.app_id,
            business_trace_id=orm.business_trace_id,
            business_correlation_id=orm.business_correlation_id,
            stream_name=orm.stream_name,
            target_url=orm.target_url,
            http_method=orm.http_method,
            request_headers=dict(orm.request_headers),
            request_body=dict(orm.request_body) if orm.request_body is not None else None,
            request_s3_key=orm.request_s3_key,
            request_size_bytes=orm.request_size_bytes,
            request_sha256=orm.request_sha256,
            status=OutboundDispatchStatus(orm.status),
            response_status_code=orm.response_status_code,
            response_headers=dict(orm.response_headers)
            if orm.response_headers is not None
            else None,
            response_body=dict(orm.response_body) if orm.response_body is not None else None,
            response_s3_key=orm.response_s3_key,
            duration_ms=orm.duration_ms,
            attempt_number=orm.attempt_number,
            error_message=orm.error_message,
            sent_at=orm.sent_at,
        )

    @staticmethod
    def _to_orm_model(domain: OutboundRecord) -> OutboundRecordModel:
        """Strict type-safe Data Mapper from Domain Aggregate to ORM model."""
        return OutboundRecordModel(
            id=domain.id,
            tenant_id=domain.tenant_id,
            connection_id=domain.connection_id,
            app_id=domain.app_id,
            business_trace_id=domain.business_trace_id,
            business_correlation_id=domain.business_correlation_id,
            stream_name=domain.stream_name,
            target_url=domain.target_url,
            http_method=domain.http_method,
            request_headers=domain.request_headers,
            request_body=domain.request_body,
            request_s3_key=domain.request_s3_key,
            request_size_bytes=domain.request_size_bytes,
            request_sha256=domain.request_sha256,
            status=domain.status.value,
            response_status_code=domain.response_status_code,
            response_headers=domain.response_headers,
            response_body=domain.response_body,
            response_s3_key=domain.response_s3_key,
            duration_ms=domain.duration_ms,
            attempt_number=domain.attempt_number,
            error_message=domain.error_message,
            sent_at=domain.sent_at,
        )

    def _drain_events(self, record: OutboundRecord) -> None:
        """Extracts aggregate domain events and stages them into the transactional outbox."""
        for event in record.domain_events:
            outbox_id = generate_id(IpOutboxRecord.ID_PREFIX)
            event_name = event.event_name
            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id() or record.tenant_id

            outbox_event = IpOutboxRecord(
                id=outbox_id,
                idempotency_key=event.idempotency_key,
                tenant_id=tenant_id,
                event_type=event_name,
                payload=payload_dict,
                status=OutboxStatus.PENDING,
            )
            self._session.add(outbox_event)

        record.clear_domain_events()

    async def save(self, record: OutboundRecord) -> None:
        orm = self._to_orm_model(record)
        self._session.add(orm)
        self._drain_events(record)

    async def get_by_id(self, record_id: str, tenant_id: str) -> OutboundRecord | None:
        stmt = select(OutboundRecordModel).where(
            OutboundRecordModel.id == record_id,
            OutboundRecordModel.tenant_id == tenant_id,
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return self._to_domain_model(orm)

    async def get_by_trace_id(
        self, business_trace_id: str, tenant_id: str
    ) -> Sequence[OutboundRecord]:
        stmt = (
            select(OutboundRecordModel)
            .where(
                OutboundRecordModel.business_trace_id == business_trace_id,
                OutboundRecordModel.tenant_id == tenant_id,
            )
            .order_by(OutboundRecordModel.sent_at.asc())
        )
        result = await self._session.execute(stmt)
        return [self._to_domain_model(orm) for orm in result.scalars().all()]
