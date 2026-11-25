"""Universal storage domain enums (core/platform/packages/storage)."""

from __future__ import annotations

from enum import StrEnum


class CompressionCodec(StrEnum):
    """Supported compression codecs for object storage payloads."""

    NONE = "none"
    GZIP = "gzip"
    ZSTD = "zstd"

    @property
    def file_extension(self) -> str:
        match self:
            case CompressionCodec.NONE:
                return ""
            case CompressionCodec.GZIP:
                return ".gz"
            case CompressionCodec.ZSTD:
                return ".zst"


class StorageTier(StrEnum):
    """Storage tier classification."""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    ARCHIVE = "archive"


class StorageBackend(StrEnum):
    """Supported storage backend drivers for PayloadStoragePort."""

    S3 = "s3"
    MINIO = "minio"
    FILE = "file"
    FILESYSTEM = "filesystem"
    NFS = "nfs"
    POSIX = "posix"

    @property
    def is_filesystem(self) -> bool:
        return self in {
            StorageBackend.FILE,
            StorageBackend.FILESYSTEM,
            StorageBackend.NFS,
            StorageBackend.POSIX,
        }
