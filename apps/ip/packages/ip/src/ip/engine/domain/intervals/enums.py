"""High-Frequency Interval Data Plane Domain Enumerations."""

from enum import StrEnum


class StreamVelocityMode(StrEnum):
    """Stream processing velocity classification for the Data Plane."""

    ENTITY_TRANSACTIONAL = "ENTITY_TRANSACTIONAL"  # Row-level OLTP (< 100 events/s)
    TIMESERIES_COLUMNAR = "TIMESERIES_COLUMNAR"  # Vectorized Columnar (1,000+ readings/s)


class PriorityLane(StrEnum):
    """Three-Lane QoS Isolation lanes preventing bulk interval batches from starving real-time outages."""

    P0_CRITICAL = "P0_CRITICAL"  # Outage / Tamper / Disconnect-Reconnect (< 2s SLA)
    P1_LIVE = "P1_LIVE"  # Current 15-min interval window (< 30s SLA)
    P2_BULK_REPLAY = "P2_BULK_REPLAY"  # Historical backfill & SFTP drops (< 15m SLA)


class BatchManifestStatus(StrEnum):
    """Lifecycle status of an interval macro-batch in ip_batch_manifests."""

    INGESTED = "INGESTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class CimQualityStatus(StrEnum):
    """IEC 61968-9 / CIM ReadingQuality flags for interval readings."""

    VALID = "VALID"
    ESTIMATED_VEE = "ESTIMATED_VEE"
    ESTIMATED_MANUAL = "ESTIMATED_MANUAL"
    DST_AMBIGUOUS = "DST_AMBIGUOUS"
    POWER_DOWN = "POWER_DOWN"
    QUARANTINED_SPIKE = "QUARANTINED_SPIKE"


class TariffBucket(StrEnum):
    """Time-of-Use (TOU) tariff period buckets for interval aggregation."""

    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF_PEAK = "OFF_PEAK"


class IntervalPayloadFormat(StrEnum):
    """Supported wire/file formats for L1 raw interval batch drops."""

    JSON_ARRAY = "JSON_ARRAY"
    CSV = "CSV"
    ARROW_IPC = "ARROW_IPC"
    PARQUET = "PARQUET"


__all__ = [
    "BatchManifestStatus",
    "CimQualityStatus",
    "IntervalPayloadFormat",
    "PriorityLane",
    "StreamVelocityMode",
    "TariffBucket",
]
