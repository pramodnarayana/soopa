"""Domain events for the Integration Platform bounded context."""

from dataclasses import dataclass

from seedwork.events import DomainEvent

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class ConnectionCreatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str
    connection_name: str
    auth_type: str

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionActivatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_ACTIVATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionDeactivatedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_DEACTIVATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionRelinkedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    app_id: str
    relinked_at: str

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_RELINKED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ConnectionErrorRecordedEvent(DomainEvent):
    connection_id: str
    tenant_id: str
    error_code: str
    error_message: str

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_ERROR_RECORDED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class InboundRecordCreatedEvent(DomainEvent):
    """Domain event emitted when an external inbound record is durably stored in L1."""

    record_id: str
    tenant_id: str
    connection_id: str
    trace_id: str
    correlation_id: str | None
    stream_name: str
    payload_size_bytes: int
    payload_sha256: str
    is_inlined: bool
    s3_key: str | None
    app_id: str = ""
    ingestion_mode: str = "PUSH_FULL"
    sync_run_id: str | None = None
    generation_id: int | None = None
    external_event_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @property
    def event_name(self) -> str:
        return IpEventType.INBOUND_RECORD_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ReplicaRecordUpdatedEvent(DomainEvent):
    """Domain event emitted when an L2 universal replica snapshot is created or updated."""

    record_id: str
    tenant_id: str
    connection_id: str
    app_id: str
    entity_type: str
    entity_id: str
    data_hash: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @property
    def event_name(self) -> str:
        return IpEventType.REPLICA_RECORD_UPDATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ReplicaRecordChangedEvent(DomainEvent):
    """Domain event emitted when an L2 universal replica changes (INSERT, UPDATE, TOMBSTONE)."""

    record_id: str
    tenant_id: str
    connection_id: str
    stream: str
    record_key: str
    outcome: str
    version: int
    data_hash: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @property
    def event_name(self) -> str:
        return IpEventType.REPLICA_RECORD_CHANGED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class NormalizedRecordCreatedEvent(DomainEvent):
    """Domain event emitted when an L3 canonical normalization completes."""

    record_id: str
    tenant_id: str
    connection_id: str
    canonical_type: str
    source_id: str
    trace_id: str
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @property
    def event_name(self) -> str:
        return IpEventType.NORMALIZED_RECORD_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class OutboundRecordCreatedEvent(DomainEvent):
    """Domain event emitted when an external outbound dispatch is executed."""

    record_id: str
    tenant_id: str
    connection_id: str
    app_id: str
    trace_id: str
    correlation_id: str | None
    stream_name: str
    status: str
    response_status_code: int | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0

    @property
    def event_name(self) -> str:
        return IpEventType.OUTBOUND_RECORD_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class StreamStateCheckpointedEvent(DomainEvent):
    """Domain event emitted when an incremental sync stream advances its cursor checkpoint."""

    state_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    cursor_value: str
    records_synced_count: int

    @property
    def event_name(self) -> str:
        return IpEventType.STREAM_STATE_CHECKPOINTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class SyncRunStartedEvent(DomainEvent):
    """Domain event emitted when a pull sync run begins execution."""

    run_id: str
    tenant_id: str
    connection_id: str
    stream: str
    kind: str
    generation_id: int
    start_checkpoint: str | None
    trace_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.SYNC_RUN_STARTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class SyncRunCompletedEvent(DomainEvent):
    """Domain event emitted when a pull sync run finishes successfully."""

    run_id: str
    tenant_id: str
    connection_id: str
    stream: str
    kind: str
    generation_id: int
    end_checkpoint: str | None
    pages_count: int
    records_count: int
    bytes_count: int
    trace_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.SYNC_RUN_COMPLETED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class SyncRunFailedEvent(DomainEvent):
    """Domain event emitted when a pull sync run fails with a terminal error."""

    run_id: str
    tenant_id: str
    connection_id: str
    stream: str
    kind: str
    generation_id: int
    error_code: str
    error_message: str
    trace_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.SYNC_RUN_FAILED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class GenerationCompletedEvent(DomainEvent):
    """Domain event emitted when a full refresh completes, triggering L2 tombstone sweep."""

    tenant_id: str
    connection_id: str
    stream: str
    generation_id: int
    trace_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.GENERATION_COMPLETED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class FetchRecordRequestedEvent(DomainEvent):
    """Domain event emitted when a PUSH_THIN notice requests an async fetch."""

    tenant_id: str
    connection_id: str
    stream: str
    record_id: str
    notice_inbound_record_id: str
    trace_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.FETCH_RECORD_REQUESTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
