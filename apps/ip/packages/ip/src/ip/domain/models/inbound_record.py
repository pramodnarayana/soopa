"""InboundRecord aggregate root for Layer 1 Raw Audit Evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from ip.domain.constants import IpDomainIdPrefix
from ip.domain.events import InboundRecordCreatedEvent
from ip.domain.types import JsonDict
from seedwork.models import AggregateRoot
from seedwork.utils import generate_id


def compute_payload_sha256(payload_bytes: bytes) -> str:
    """Computes a SHA-256 hash for raw payload change detection."""
    return hashlib.sha256(payload_bytes).hexdigest()


@dataclass(kw_only=True, eq=False)
class InboundRecord(AggregateRoot):
    """Aggregate Root representing an immutable external raw record in Layer 1 Ingestion."""

    ID_PREFIX: ClassVar[str] = IpDomainIdPrefix.INBOUND_RECORD

    id: str
    tenant_id: str
    connection_id: str
    business_trace_id: str
    business_correlation_id: str | None = None
    stream_name: str
    raw_payload: JsonDict | None = None
    s3_key: str | None = None
    payload_size_bytes: int
    payload_sha256: str
    headers: JsonDict = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
        payload_bytes: bytes,
        is_inlined: bool,
        raw_payload: JsonDict | None = None,
        s3_key: str | None = None,
        headers: JsonDict | None = None,
        business_correlation_id: str | None = None,
        business_trace_id: str | None = None,
    ) -> InboundRecord:
        record_id = generate_id(cls.ID_PREFIX)
        trace_id = business_trace_id or generate_id(IpDomainIdPrefix.TRACE)
        size_bytes = len(payload_bytes)
        sha256_hash = compute_payload_sha256(payload_bytes)

        record = cls(
            id=record_id,
            tenant_id=tenant_id,
            connection_id=connection_id,
            business_trace_id=trace_id,
            business_correlation_id=business_correlation_id,
            stream_name=stream_name,
            raw_payload=raw_payload if is_inlined else None,
            s3_key=s3_key if not is_inlined else None,
            payload_size_bytes=size_bytes,
            payload_sha256=sha256_hash,
            headers=dict(headers or {}),
            received_at=datetime.now(UTC),
        )

        record.add_domain_event(
            InboundRecordCreatedEvent(
                record_id=record_id,
                tenant_id=tenant_id,
                connection_id=connection_id,
                business_trace_id=trace_id,
                business_correlation_id=business_correlation_id,
                stream_name=stream_name,
                payload_size_bytes=size_bytes,
                payload_sha256=sha256_hash,
                is_inlined=is_inlined,
                s3_key=s3_key,
            )
        )
        return record
