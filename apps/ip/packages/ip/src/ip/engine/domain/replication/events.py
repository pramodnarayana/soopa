"""Domain events for the Ingestion and Replication aggregates."""

from dataclasses import dataclass

from seedwork.events import DomainEvent, EventProcessingLane

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class InboundRecordCreatedEvent(DomainEvent):
    """Domain event emitted when a Range Claim-Check (`1..K`) of inbound records is durably stored in L1."""

    record_id: str = ""
    batch_id: str = ""
    range_start: str = ""
    range_end: str = ""
    count: int = 1
    causation_depth: int = 0
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
        self._normalize_record_identifiers()
        self._normalize_range_bounds()
        if self.lane is None:
            object.__setattr__(self, "lane", self._derive_default_lane())

    def _normalize_record_identifiers(self) -> None:
        is_multi_range_claim_check = bool(self.batch_id) and self.count > 1
        if not is_multi_range_claim_check:
            if not self.record_ids and self.record_id:
                object.__setattr__(self, "record_ids", (self.record_id,))
            elif self.record_ids and not self.record_id:
                object.__setattr__(self, "record_id", self.record_ids[0])
        elif not self.record_id and self.range_start:
            object.__setattr__(self, "record_id", self.range_start)

    def _normalize_range_bounds(self) -> None:
        if not self.range_start:
            fallback_start = self.record_ids[0] if self.record_ids else self.record_id
            if fallback_start:
                object.__setattr__(self, "range_start", fallback_start)
        if not self.range_end:
            fallback_end = (
                self.record_ids[-1] if self.record_ids else (self.range_start or self.record_id)
            )
            if fallback_end:
                object.__setattr__(self, "range_end", fallback_end)
        if self.count <= 1 and len(self.record_ids) > 1:
            object.__setattr__(self, "count", len(self.record_ids))

    def _derive_default_lane(self) -> EventProcessingLane:
        is_bulk = (
            self.count > 1 or len(self.record_ids) > 1 or self.ingestion_mode.startswith("PULL_")
        )
        return EventProcessingLane.BULK if is_bulk else EventProcessingLane.REALTIME

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
class ConnectionEntityCheckpointedEvent(DomainEvent):
    """Domain event emitted when a subscribed connection entity advances its sync checkpoint."""

    entity_id: str
    tenant_id: str
    connection_id: str
    stream_name: str
    cursor_value: str
    records_synced_count: int

    @property
    def event_name(self) -> str:
        return IpEventType.CONNECTION_ENTITY_CHECKPOINTED

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
class SyncRunCancelledEvent(DomainEvent):
    """Domain event emitted when an active or pending pull sync run is cancelled."""

    run_id: str
    tenant_id: str
    connection_id: str
    stream: str
    kind: str
    generation_id: int
    reason: str
    trace_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.SYNC_RUN_CANCELLED

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
