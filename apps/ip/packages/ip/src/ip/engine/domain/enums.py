"""Integration Platform (IP) Domain Enumerations."""

from enum import StrEnum


class IpEventType(StrEnum):
    """Canonical domain event types emitted by the Integration Platform."""

    CONNECTION_CREATED = "ip.connection.created"
    CONNECTION_ACTIVATED = "ip.connection.activated"
    CONNECTION_DEACTIVATED = "ip.connection.deactivated"
    CONNECTION_DELETED = "ip.connection.deleted"
    CONNECTION_RELINKED = "ip.connection.relinked"
    CONNECTION_ERROR_RECORDED = "ip.connection.error_recorded"
    INBOUND_RECORD_CREATED = "ip.inbound_record.created"
    SYNC_RUN_REQUESTED = "ip.sync_run.requested"
    SYNC_RUN_STARTED = "ip.sync_run.started"
    SYNC_RUN_COMPLETED = "ip.sync_run.completed"
    SYNC_RUN_FAILED = "ip.sync_run.failed"
    SYNC_RUN_CANCELLED = "ip.sync_run.cancelled"
    GENERATION_COMPLETED = "ip.generation.completed"
    FETCH_RECORD_REQUESTED = "ip.fetch_record.requested"
    REPLICA_RECORD_CHANGED = "ip.replica_record.changed"
    NORMALIZED_RECORD_CREATED = "ip.normalized_record.created"
    CANONICAL_RECORD_CHANGED = "ip.canonical_record.changed"
    TRANSFORMATION_CHANGED = "ip.transformation.changed"
    TRANSFORMATION_VERSION_PROMOTED = "ip.transformation_version.promoted"
    STITCH_REGISTERED = "ip.stitch.registered"
    OUTBOUND_RECORD_CREATED = "ip.outbound_record.created"
    STREAM_STATE_CHECKPOINTED = "ip.stream_state.checkpointed"


class IpIdPrefix(StrEnum):
    """Domain-specific entity ID prefixes for the Integration Platform (IP) bounded context."""

    TRACE = "ip_trc"
    TRACE_EVENT = "ip_trace_evt"
    INBOUND_RECORD = "ip_inb"
    CONNECTION = "ip_conn"
    CATALOG = "ip_cat"
    STREAM = "ip_strm"
    REPLICA = "ip_rep"
    REPLICA_REJECTION = "ip_rej"
    NORMALIZED = "ip_nrm"
    CANONICAL = "ip_canon"
    OUTBOUND_RECORD = "ip_out"
    OUTBOUND_DISPATCH = "ip_disp"
    OUTBOX = "ip_obx"
    GEM = "ip_gem"
    STREAM_STATE = "ip_cst"
    MDM_READING = "ip_mdmr"
    MDM_SERVICE_POINT = "ip_mdms"
    TMS_LOAD = "ip_tmsl"
    TMS_CARRIER = "ip_tmsc"
    SYNC_RUN = "ip_sync"
    TRANSFORMATION = "ip_xfrm"
    STITCH = "ip_stch"
    NORMALIZATION_LEDGER = "ip_nlg"
    NORMALIZATION_REJECTION = "ip_nrj"
    SHADOW_DIFF = "ip_sdiff"
    PENDING_REFERENCE = "ip_pref"


class IpOutboxSource(StrEnum):
    """Canonical CloudEvents source identifiers for IP outbox streams."""

    CONTROL_PLANE = "soopa.ip.control_plane"
    DATA_PLANE = "soopa.ip.data_plane"


class IpOutboxChannel(StrEnum):
    """PostgreSQL LISTEN/NOTIFY channel names for IP outbox wakeup."""

    CONTROL_PLANE = "ip_cp_outbox_channel"
    DATA_PLANE = "ip_dp_outbox_channel"


class IpJobName(StrEnum):
    """Scheduled background job identifiers for IP Control Plane and Data Plane."""

    IP_CONTROL_PLANE_OUTBOX_SWEEPER = "IP_CONTROL_PLANE_OUTBOX_SWEEPER"
    IP_CONTROL_PLANE_OUTBOX_CLEANUP = "IP_CONTROL_PLANE_OUTBOX_CLEANUP"
    IP_DATA_PLANE_OUTBOX_SWEEPER = "IP_DATA_PLANE_OUTBOX_SWEEPER"
    IP_DATA_PLANE_OUTBOX_CLEANUP = "IP_DATA_PLANE_OUTBOX_CLEANUP"
    IP_DATA_RETENTION_CLEANUP = "IP_DATA_RETENTION_CLEANUP"


class PipelineStage(StrEnum):
    """Five-stage SEDA pipeline execution stages."""

    INGEST = "L1_INGEST"
    REPLICA = "L2_REPLICA"
    NORMALIZE = "L3_NORMALIZE"
    HYDRATE = "L4_HYDRATE"
    DELIVER = "L5_DELIVER"


__all__ = [
    "IpEventType",
    "IpIdPrefix",
    "IpJobName",
    "IpOutboxChannel",
    "IpOutboxSource",
    "PipelineStage",
]
