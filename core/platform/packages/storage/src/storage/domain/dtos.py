"""Universal storage domain DTOs (core/platform/packages/storage)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from storage.domain.enums import CompressionCodec, StorageTier


@dataclass(frozen=True, slots=True)
class StorageObjectMetadataDTO:
    """Metadata describing an object in cloud/minio storage."""

    storage_uri: str
    bucket: str
    key: str
    size_bytes: int
    sha256: str
    content_type: str
    compression: CompressionCodec
    tier: StorageTier
    created_at_utc: datetime


@dataclass(frozen=True, slots=True)
class MultipartUploadPartDTO:
    """Part representation for multipart upload operations."""

    part_number: int
    etag: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class CoalescerMetricsDTO:
    """Snapshot metrics for sliding window micro-batch buffer."""

    tenant_id: str
    stream_name: str
    buffered_count: int
    batch_size_threshold: int
    window_duration_seconds: float
    total_flushes: int
    total_records_flushed: int
