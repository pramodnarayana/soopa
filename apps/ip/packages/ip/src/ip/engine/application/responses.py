"""Strict boundary response and read DTOs for the Integration Platform.

All DTOs are pure Python @dataclass(frozen=True) instances.
Pydantic BaseModels and ORM models must NEVER cross into this layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.domain.types import JsonDict
from strace.domain import TraceEvent, TraceLineageItemDTO

from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.exceptions import IpError
from ip.engine.domain.normalization.ledger import NormalizationRejectionEntry
from ip.engine.domain.normalization.normalized_record import GlobalEntityMap, NormalizedRecord
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.trace import IpTraceStatus
from ip.engine.ports.outbound.connector_port import AppSpecDTO


@dataclass(frozen=True)
class AppSpecResultDTO:
    """Result of retrieving dynamic connector application specification."""

    success: bool
    spec: AppSpecDTO | None = None
    error_code: str | None = None
    error_message: str | None = None
    error: IpError | None = None

    @classmethod
    def ok(cls, spec: AppSpecDTO) -> AppSpecResultDTO:
        return cls(success=True, spec=spec)

    @classmethod
    def from_error(cls, error: IpError) -> AppSpecResultDTO:
        return cls(
            success=False,
            error=error,
            error_code=error.code.value,
            error_message=error.message,
        )


@dataclass(frozen=True)
class ConnectionOperationResultDTO:
    """Structured result returned by connection lifecycle operations."""

    success: bool
    connection: ConnectionDTO | None = None
    error_code: str | None = None
    error_message: str | None = None
    error: IpError | None = None

    @classmethod
    def ok(cls, connection: ConnectionDTO) -> ConnectionOperationResultDTO:
        return cls(success=True, connection=connection)

    @classmethod
    def from_error(cls, error: IpError) -> ConnectionOperationResultDTO:
        return cls(
            success=False,
            error=error,
            error_code=error.code.value,
            error_message=error.message,
        )


@dataclass(frozen=True)
class ConnectionDTO:
    """Safe, read-only representation of a connection for boundaries."""

    id: str
    tenant_id: str
    app_id: str
    name: str
    auth_type: str
    public_config: JsonDict
    status: str
    connection_fingerprint: str
    token_expires_at: str | None
    last_refreshed_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: str
    updated_at: str
    deactivated_at: str | None

    @classmethod
    def from_domain(cls, conn: Connection) -> ConnectionDTO:
        return cls(
            id=conn.id,
            tenant_id=conn.tenant_id,
            app_id=conn.app_id,
            name=conn.name,
            auth_type=conn.auth_type.value,
            public_config=dict(conn.public_config),
            status=conn.status.value,
            connection_fingerprint=conn.connection_fingerprint,
            token_expires_at=conn.token_expires_at,
            last_refreshed_at=conn.last_refreshed_at,
            last_error_code=conn.last_error_code,
            last_error_message=conn.last_error_message,
            created_at=conn.created_at,
            updated_at=conn.updated_at,
            deactivated_at=conn.deactivated_at,
        )


IpTraceLineageItemDTO = TraceLineageItemDTO


@dataclass(frozen=True, kw_only=True)
class IpTraceDTO:
    """End-to-end 5-layer waterfall snapshot of a single Integration Platform trace."""

    trace_id: str
    tenant_id: str
    correlation_id: str | None
    original_trace_id: str
    parent_trace_id: str | None
    replay_count: int
    status: IpTraceStatus
    inbound_record: InboundRecord | None = None
    replica_records: tuple[ReplicaRecord, ...] = ()
    replica_rejections: tuple[ReplicaRejection, ...] = ()
    normalized_records: tuple[NormalizedRecord, ...] = ()
    normalization_rejections: tuple[NormalizationRejectionEntry, ...] = ()
    entity_mappings: tuple[GlobalEntityMap, ...] = ()
    outbound_records: tuple[OutboundRecord, ...] = ()
    trace_events: tuple[TraceEvent, ...] = ()


__all__ = [
    "AppSpecResultDTO",
    "ConnectionDTO",
    "ConnectionOperationResultDTO",
    "IpTraceDTO",
    "IpTraceLineageItemDTO",
]
