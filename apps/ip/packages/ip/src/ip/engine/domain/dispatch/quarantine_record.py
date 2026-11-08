"""QuarantineRecord value object for the Layer-5 tenant-scoped Dead-Letter Ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id

from ip.engine.domain.constants import IpIdPrefix


@dataclass(frozen=True, kw_only=True)
class QuarantineRecord:
    """Immutable tenant-scoped DLQ entry capturing terminally failed outbound dispatches."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.QUARANTINE_RECORD.value

    id: str
    tenant_id: str
    connection_id: str
    outbound_record_id: str
    stream_name: str
    idempotency_key: str | None = None
    trace_id: str
    correlation_id: str | None = None
    failure_category: str
    error_code: str | None = None
    error_message: str
    response_status_code: int | None = None
    attempt_count: int = 1
    request_body: JsonDict | None = None
    request_s3_key: str | None = None
    response_body: JsonDict | None = None
    response_s3_key: str | None = None
    quarantined_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        connection_id: str,
        outbound_record_id: str,
        stream_name: str,
        trace_id: str,
        failure_category: str,
        error_message: str,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        error_code: str | None = None,
        response_status_code: int | None = None,
        attempt_count: int = 1,
        request_body: JsonDict | None = None,
        request_s3_key: str | None = None,
        response_body: JsonDict | None = None,
        response_s3_key: str | None = None,
    ) -> QuarantineRecord:
        return cls(
            id=generate_id(cls.ID_PREFIX),
            tenant_id=tenant_id,
            connection_id=connection_id,
            outbound_record_id=outbound_record_id,
            stream_name=stream_name,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            correlation_id=correlation_id,
            failure_category=failure_category,
            error_code=error_code,
            error_message=error_message,
            response_status_code=response_status_code,
            attempt_count=max(1, attempt_count),
            request_body=dict(request_body) if request_body is not None else None,
            request_s3_key=request_s3_key,
            response_body=dict(response_body) if response_body is not None else None,
            response_s3_key=response_s3_key,
            quarantined_at=datetime.now(UTC),
        )


__all__ = ["QuarantineRecord"]
