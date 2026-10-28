"""Domain events for the Integration Platform bounded context."""

from dataclasses import dataclass

from seedwork.events import DomainEvent, EventProcessingLane

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
    """Domain event emitted when one or more external inbound records are durably stored in L1."""

    record_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    stream_name: str = ""
    payload_size_bytes: int = 0
    payload_sha256: str = ""
    is_inlined: bool = True
    s3_key: str | None = None
    app_id: str = ""
    ingestion_mode: str = "PUSH_FULL"
    sync_run_id: str | None = None
    generation_id: int | None = None
    external_event_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    record_ids: tuple[str, ...] = ()
    lane: EventProcessingLane | None = None

    def __post_init__(self) -> None:
        if not self.record_ids and self.record_id:
            object.__setattr__(self, "record_ids", (self.record_id,))
        elif self.record_ids and not self.record_id:
            object.__setattr__(self, "record_id", self.record_ids[0])
        if self.lane is None:
            resolved_lane = (
                EventProcessingLane.BULK
                if (len(self.record_ids) > 1 or self.ingestion_mode.startswith("PULL_"))
                else EventProcessingLane.REALTIME
            )
            object.__setattr__(self, "lane", resolved_lane)

    @property
    def event_name(self) -> str:
        return IpEventType.INBOUND_RECORD_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME


@dataclass(frozen=True)
class ReplicaRecordChangedEvent(DomainEvent):
    """Domain event emitted when one or more L2 universal replicas change (INSERT, UPDATE, TOMBSTONE)."""

    record_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    stream: str = ""
    record_key: str = ""
    outcome: str = ""
    version: int = 1
    data_hash: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    record_ids: tuple[str, ...] = ()
    lane: EventProcessingLane | None = None

    def __post_init__(self) -> None:
        if not self.record_ids and self.record_id:
            object.__setattr__(self, "record_ids", (self.record_id,))
        elif self.record_ids and not self.record_id:
            object.__setattr__(self, "record_id", self.record_ids[0])
        if self.lane is None:
            resolved_lane = (
                EventProcessingLane.BULK
                if len(self.record_ids) > 1
                else EventProcessingLane.REALTIME
            )
            object.__setattr__(self, "lane", resolved_lane)

    @property
    def event_name(self) -> str:
        return IpEventType.REPLICA_RECORD_CHANGED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME


@dataclass(frozen=True)
class NormalizedRecordCreatedEvent(DomainEvent):
    """Domain event emitted when an L3 canonical normalization completes."""

    record_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    canonical_type: str = ""
    source_id: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    record_ids: tuple[str, ...] = ()
    lane: EventProcessingLane | None = None

    def __post_init__(self) -> None:
        if not self.record_ids and self.record_id:
            object.__setattr__(self, "record_ids", (self.record_id,))
        elif self.record_ids and not self.record_id:
            object.__setattr__(self, "record_id", self.record_ids[0])
        if self.lane is None:
            resolved_lane = (
                EventProcessingLane.BULK
                if len(self.record_ids) > 1
                else EventProcessingLane.REALTIME
            )
            object.__setattr__(self, "lane", resolved_lane)

    @property
    def event_name(self) -> str:
        return IpEventType.NORMALIZED_RECORD_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME


@dataclass(frozen=True)
class CanonicalRecordChangedEvent(DomainEvent):
    """Domain event emitted when one or more canonical domain records are upserted or tombstoned."""

    tenant_id: str = ""
    connection_id: str = ""
    canonical_type: str = ""
    source_id: str = ""
    action: str = "UPSERT"
    trace_id: str = ""
    transformation_id: str = ""
    transformation_version: int = 1
    replica_id: str = ""
    replica_version: int = 1
    correlation_id: str | None = None
    changed_fields: tuple[str, ...] = ()
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    record_ids: tuple[str, ...] = ()
    lane: EventProcessingLane | None = None

    def __post_init__(self) -> None:
        if not self.record_ids and self.source_id:
            object.__setattr__(self, "record_ids", (self.source_id,))
        elif self.record_ids and not self.source_id:
            object.__setattr__(self, "source_id", self.record_ids[0])
        if self.lane is None:
            resolved_lane = (
                EventProcessingLane.BULK
                if len(self.record_ids) > 1
                else EventProcessingLane.REALTIME
            )
            object.__setattr__(self, "lane", resolved_lane)

    @property
    def event_name(self) -> str:
        return IpEventType.CANONICAL_RECORD_CHANGED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME


@dataclass(frozen=True)
class TransformationChangedEvent(DomainEvent):
    """Domain event emitted when a stream transformation is created or updated."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    mode: str
    shadow_transformation_version: int | None = None

    @property
    def event_name(self) -> str:
        return IpEventType.TRANSFORMATION_CHANGED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class TransformationVersionPromotedEvent(DomainEvent):
    """Domain event emitted when a candidate shadow transformation version is promoted to active."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    promoted_version: int
    previous_version: int

    @property
    def event_name(self) -> str:
        return IpEventType.TRANSFORMATION_VERSION_PROMOTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class StitchRegisteredEvent(DomainEvent):
    """Domain event emitted when a Stitch is registered or updated in the Control Plane."""

    stitch_id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    canonical_event_type: str
    is_trigger: bool
    is_active: bool

    @property
    def event_name(self) -> str:
        return IpEventType.STITCH_REGISTERED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class OutboundRecordCreatedEvent(DomainEvent):
    """Domain event emitted when one or more external outbound dispatches are staged or executed."""

    record_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    app_id: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    stream_name: str = ""
    status: str = ""
    response_status_code: int | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    record_ids: tuple[str, ...] = ()
    lane: EventProcessingLane | None = None

    def __post_init__(self) -> None:
        if not self.record_ids and self.record_id:
            object.__setattr__(self, "record_ids", (self.record_id,))
        elif self.record_ids and not self.record_id:
            object.__setattr__(self, "record_id", self.record_ids[0])
        if self.lane is None:
            resolved_lane = (
                EventProcessingLane.BULK
                if len(self.record_ids) > 1
                else EventProcessingLane.REALTIME
            )
            object.__setattr__(self, "lane", resolved_lane)

    @property
    def event_name(self) -> str:
        return IpEventType.OUTBOUND_RECORD_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME


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
class SyncRunRequestedEvent(DomainEvent):
    """Domain event emitted when a pull sync run is requested via API or cron scheduler."""

    tenant_id: str
    connection_id: str
    stream: str
    kind: str
    trace_id: str
    correlation_id: str | None = None

    @property
    def event_name(self) -> str:
        return IpEventType.SYNC_RUN_REQUESTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


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

    def get_trace_id(self) -> str | None:
        return self.trace_id or None


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

    def get_trace_id(self) -> str | None:
        return self.trace_id or None


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

    def get_trace_id(self) -> str | None:
        return self.trace_id or None


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

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class FetchRecordRequestedEvent(DomainEvent):
    """Domain event emitted when one or more PUSH_THIN notices request an async fetch."""

    tenant_id: str = ""
    connection_id: str = ""
    stream: str = ""
    record_id: str = ""
    notice_inbound_record_id: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    record_ids: tuple[str, ...] = ()
    lane: EventProcessingLane | None = None

    def __post_init__(self) -> None:
        if not self.record_ids and self.record_id:
            object.__setattr__(self, "record_ids", (self.record_id,))
        elif self.record_ids and not self.record_id:
            object.__setattr__(self, "record_id", self.record_ids[0])
        if self.lane is None:
            resolved_lane = (
                EventProcessingLane.BULK
                if len(self.record_ids) > 1
                else EventProcessingLane.REALTIME
            )
            object.__setattr__(self, "lane", resolved_lane)

    @property
    def event_name(self) -> str:
        return IpEventType.FETCH_RECORD_REQUESTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME
