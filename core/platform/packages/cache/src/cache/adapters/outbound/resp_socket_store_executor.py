"""
Zero-Dependency Pooled Async RESP Wire Store Executor (`resp_socket_store_executor`).

Communicates directly with Valkey / Redis 7+ clusters over persistent `asyncio` TCP
streams using binary-safe RESP2 framing, executing atomic Lua CAS scripts, `HMGET`,
`DEL`, and `SET ... NX PX` refresh leases with first-class error isolation.
"""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Awaitable, Callable, Sequence
from typing import Final, Protocol

import structlog

from cache.domain.constants import (
    HASH_FIELD_PAYLOAD,
    HASH_FIELD_SOFT_EXP_MS,
    HASH_FIELD_WATERMARK,
    CacheStoreOperationStatus,
)
from cache.domain.projection import StoreCasExecutionDTO, StoredHashProjectionDTO
from cache.ports.outbound.cache_store_executor_port import AtomicCacheStoreExecutorPort

logger = structlog.get_logger(__name__)

_CRLF: Final[bytes] = b"\r\n"
RespFrame = str | int | list["RespFrame"] | None


class AsyncByteWriterPort(Protocol):
    """Structural async stream writer protocol satisfied by `asyncio.StreamWriter`."""

    def is_closing(self) -> bool: ...

    def write(self, _data: bytes, /) -> None: ...

    async def drain(self) -> None: ...

    def close(self) -> None: ...

    async def wait_closed(self) -> None: ...


RespConnectionPair = tuple[asyncio.StreamReader, AsyncByteWriterPort]
RespConnectionFactory = Callable[[], Awaitable[RespConnectionPair]]


class RespProtocolError(RuntimeError):
    """Raised when the remote RESP server returns a protocol error frame (`-ERR`)."""


class RespProtocolCodec:
    """Binary-safe encoder and parser for RESP2 frames."""

    @staticmethod
    def encode_command(parts: Sequence[str]) -> bytes:
        chunks: list[bytes] = [f"*{len(parts)}\r\n".encode("ascii")]
        for item in parts:
            raw = item.encode("utf-8")
            chunks.append(f"${len(raw)}\r\n".encode("ascii"))
            chunks.append(raw)
            chunks.append(_CRLF)
        return b"".join(chunks)

    @classmethod
    async def read_frame(cls, reader: asyncio.StreamReader) -> RespFrame:
        header = await reader.readuntil(_CRLF)
        prefix = header[:1]
        body = header[1:-2].decode("utf-8")

        if prefix == b"+":
            return body
        if prefix == b"-":
            raise RespProtocolError(body)
        if prefix == b":":
            return int(body)
        if prefix == b"$":
            length = int(body)
            if length < 0:
                return None
            payload = await reader.readexactly(length + 2)
            return payload[:-2].decode("utf-8")
        if prefix == b"*":
            count = int(body)
            if count < 0:
                return None
            items: list[RespFrame] = []
            for _ in range(count):
                items.append(await cls.read_frame(reader))
            return items
        raise RespProtocolError(f"Unexpected RESP frame prefix: {prefix!r}")


class RespSocketStoreExecutor(AtomicCacheStoreExecutorPort):
    """Pooled async TCP RESP executor implementing `AtomicCacheStoreExecutorPort`."""

    def __init__(
        self,
        host: str,
        port: int = 6379,
        pool_size: int = 16,
        timeout_seconds: float = 0.25,
        connection_factory: RespConnectionFactory | None = None,
        username: str | None = None,
        password: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout_seconds
        self._pool: asyncio.Queue[RespConnectionPair] = asyncio.Queue(maxsize=pool_size)
        self._semaphore = asyncio.Semaphore(pool_size)
        self._username = username
        self._password = password
        self._ssl_context = ssl_context
        self._factory: RespConnectionFactory = (
            connection_factory if connection_factory is not None else self._open_tcp_socket
        )

    async def _open_tcp_socket(self) -> RespConnectionPair:
        reader, writer = await asyncio.open_connection(
            self._host, self._port, ssl=self._ssl_context
        )
        if self._password is not None:
            auth_cmd = (
                ["AUTH", self._username, self._password]
                if self._username
                else ["AUTH", self._password]
            )
            encoded = RespProtocolCodec.encode_command(auth_cmd)
            writer.write(encoded)
            await asyncio.wait_for(writer.drain(), timeout=self._timeout)
            resp = await asyncio.wait_for(
                RespProtocolCodec.read_frame(reader), timeout=self._timeout
            )
            if not isinstance(resp, str) or not resp.startswith("OK"):
                writer.close()
                raise ConnectionError("Redis AUTH failed on new connection")
        return reader, writer

    async def _acquire(self) -> RespConnectionPair:
        while not self._pool.empty():
            reader, writer = self._pool.get_nowait()
            if not writer.is_closing() and not reader.at_eof():
                return reader, writer
            writer.close()
        return await self._factory()

    def _release(self, pair: RespConnectionPair) -> None:
        reader, writer = pair
        if writer.is_closing() or reader.at_eof():
            return
        try:
            self._pool.put_nowait(pair)
        except asyncio.QueueFull:
            writer.close()

    async def _execute_raw(self, command: Sequence[str]) -> RespFrame:
        async with self._semaphore:
            pair = await asyncio.wait_for(self._acquire(), timeout=self._timeout)
            reader, writer = pair
            try:
                encoded = RespProtocolCodec.encode_command(command)
                writer.write(encoded)
                await asyncio.wait_for(writer.drain(), timeout=self._timeout)
                response = await asyncio.wait_for(
                    RespProtocolCodec.read_frame(reader), timeout=self._timeout
                )
                self._release(pair)
                return response
            except BaseException:
                writer.close()
                raise

    async def read_projection_hash(self, storage_key: str) -> StoredHashProjectionDTO:
        try:
            frame = await self._execute_raw(
                [
                    "HMGET",
                    storage_key,
                    HASH_FIELD_PAYLOAD,
                    HASH_FIELD_WATERMARK,
                    HASH_FIELD_SOFT_EXP_MS,
                ]
            )
            if not isinstance(frame, list) or len(frame) != 3:
                return StoredHashProjectionDTO(
                    status=CacheStoreOperationStatus.OK,
                    payload_json=None,
                    source_watermark=None,
                    soft_expiry_epoch_ms=None,
                )
            raw_payload, raw_wm, raw_soft = frame[0], frame[1], frame[2]
            if (
                not isinstance(raw_payload, str)
                or not isinstance(raw_wm, str)
                or not isinstance(raw_soft, str)
            ):
                return StoredHashProjectionDTO(
                    status=CacheStoreOperationStatus.OK,
                    payload_json=None,
                    source_watermark=None,
                    soft_expiry_epoch_ms=None,
                )
            return StoredHashProjectionDTO(
                status=CacheStoreOperationStatus.OK,
                payload_json=raw_payload,
                source_watermark=int(raw_wm),
                soft_expiry_epoch_ms=int(raw_soft),
            )
        except Exception:
            logger.exception(
                "cache_store_read_failed",
                storage_key=storage_key,
                host=self._host,
                port=self._port,
            )
            return StoredHashProjectionDTO(
                status=CacheStoreOperationStatus.UNAVAILABLE,
                payload_json=None,
                source_watermark=None,
                soft_expiry_epoch_ms=None,
            )

    async def eval_cas_script(
        self,
        *,
        script: str,
        storage_key: str,
        watermark: int,
        payload_json: str,
        soft_expiry_epoch_ms: int,
        hard_ttl_seconds: int,
    ) -> StoreCasExecutionDTO:
        try:
            frame = await self._execute_raw(
                [
                    "EVAL",
                    script,
                    "1",
                    storage_key,
                    str(watermark),
                    payload_json,
                    str(soft_expiry_epoch_ms),
                    str(hard_ttl_seconds),
                ]
            )
            return StoreCasExecutionDTO(
                status=CacheStoreOperationStatus.OK,
                applied=(frame == 1),
            )
        except Exception:
            logger.exception(
                "cache_store_cas_eval_failed",
                storage_key=storage_key,
                watermark=watermark,
            )
            return StoreCasExecutionDTO(
                status=CacheStoreOperationStatus.UNAVAILABLE,
                applied=False,
            )

    async def delete_storage_keys(self, storage_keys: Sequence[str]) -> int:
        if not storage_keys:
            return 0
        try:
            frame = await self._execute_raw(["DEL", *storage_keys])
            return int(frame) if isinstance(frame, int) else 0
        except Exception:
            logger.exception("cache_store_delete_failed", key_count=len(storage_keys))
            return 0

    async def try_acquire_refresh_lease(
        self,
        lease_key: str,
        lease_ttl_ms: int,
    ) -> bool:
        try:
            frame = await self._execute_raw(["SET", lease_key, "1", "NX", "PX", str(lease_ttl_ms)])
            return frame == "OK"
        except Exception:
            logger.exception("cache_store_lease_failed", lease_key=lease_key)
            return False

    async def close(self) -> None:
        while not self._pool.empty():
            _, writer = self._pool.get_nowait()
            writer.close()
            await writer.wait_closed()


__all__ = [
    "AsyncByteWriterPort",
    "RespConnectionFactory",
    "RespFrame",
    "RespProtocolCodec",
    "RespProtocolError",
    "RespSocketStoreExecutor",
]
