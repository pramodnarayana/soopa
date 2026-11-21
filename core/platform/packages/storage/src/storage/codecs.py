"""Compression and decompression codecs for payload storage."""

from __future__ import annotations

import gzip
import importlib
import importlib.util
from collections.abc import AsyncIterable
from types import ModuleType

from storage.domain.enums import CompressionCodec
from storage.domain.exceptions import CompressionError

_ZSTD_MODULE: ModuleType | None = (
    importlib.import_module("zstandard")
    if importlib.util.find_spec("zstandard") is not None
    else None
)


class StorageCodec:
    """Utility for compressing and decompressing byte payloads."""

    @staticmethod
    def compress(data: bytes, codec: CompressionCodec) -> bytes:
        if codec == CompressionCodec.NONE:
            return data
        if codec == CompressionCodec.GZIP:
            return gzip.compress(data, compresslevel=6)
        if codec == CompressionCodec.ZSTD:
            if _ZSTD_MODULE is not None:
                cctx = _ZSTD_MODULE.ZstdCompressor(level=3)
                compressed_res: bytes = cctx.compress(data)
                return compressed_res
            # Fallback to gzip when zstandard binary is not installed in the environment
            return gzip.compress(data, compresslevel=6)
        raise CompressionError(f"Unsupported compression codec: {codec}")

    @staticmethod
    def decompress(data: bytes, codec: CompressionCodec) -> bytes:
        if codec == CompressionCodec.NONE:
            return data
        if codec == CompressionCodec.GZIP:
            try:
                return gzip.decompress(data)
            except Exception as exc:
                raise CompressionError(f"Gzip decompression failed: {exc}") from exc
        if codec == CompressionCodec.ZSTD:
            if _ZSTD_MODULE is not None:
                try:
                    dctx = _ZSTD_MODULE.ZstdDecompressor()
                    decompressed_res: bytes = dctx.decompress(data)
                    return decompressed_res
                except Exception as exc:
                    raise CompressionError(f"Zstandard decompression failed: {exc}") from exc
            try:
                return gzip.decompress(data)
            except Exception as exc:
                raise CompressionError(f"Decompression failed: {exc}") from exc
        raise CompressionError(f"Unsupported compression codec: {codec}")

    @staticmethod
    async def compress_stream(
        stream: AsyncIterable[bytes], codec: CompressionCodec
    ) -> AsyncIterable[bytes]:
        if codec == CompressionCodec.NONE:
            async for chunk in stream:
                yield chunk
            return

        chunks: list[bytes] = []
        async for chunk in stream:
            chunks.append(chunk)
        compressed = StorageCodec.compress(b"".join(chunks), codec)
        yield compressed
