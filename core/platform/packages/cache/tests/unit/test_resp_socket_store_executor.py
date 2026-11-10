from __future__ import annotations

import asyncio

import pytest

from cache.adapters.outbound.resp_socket_store_executor import (
    RespFrame,
    RespProtocolCodec,
    RespProtocolError,
    RespSocketStoreExecutor,
)
from cache.domain.constants import (
    UPSERT_IF_NEWER_WATERMARK_LUA,
    CacheStoreOperationStatus,
)


class _InMemoryRespPairHarness:
    """In-memory bidirectional `StreamReader` / `StreamWriter` pair speaking real RESP2."""

    def __init__(self, *, fail_with_protocol_error: bool = False) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._leases: set[str] = set()
        self._fail = fail_with_protocol_error

    async def open_connection(self) -> tuple[asyncio.StreamReader, _LoopbackStreamWriter]:
        client_reader = asyncio.StreamReader()
        server_reader = asyncio.StreamReader()
        server_task = asyncio.create_task(self._serve_loop(server_reader, client_reader))
        writer = _LoopbackStreamWriter(server_reader, server_task)
        return client_reader, writer

    def _dispatch_command(self, cmd: list[RespFrame]) -> bytes:
        if self._fail:
            return b"-ERR simulated cluster failover\r\n"
        verb = str(cmd[0]).upper()
        if verb == "HMGET":
            return self._handle_hmget(cmd)
        if verb == "EVAL":
            return self._handle_eval(cmd)
        if verb == "DEL":
            return self._handle_del(cmd)
        if verb == "SET":
            return self._handle_set(cmd)
        return b"-ERR unknown command\r\n"

    def _handle_hmget(self, cmd: list[RespFrame]) -> bytes:
        key = str(cmd[1])
        fields = [str(f) for f in cmd[2:]]
        stored = self._hashes.get(key, {})
        parts = [f"*{len(fields)}\r\n".encode()]
        for field in fields:
            val = stored.get(field)
            if val is None:
                parts.append(b"$-1\r\n")
            else:
                enc = val.encode("utf-8")
                parts.append(f"${len(enc)}\r\n".encode() + enc + b"\r\n")
        return b"".join(parts)

    def _handle_eval(self, cmd: list[RespFrame]) -> bytes:
        key = str(cmd[3])
        wm = int(str(cmd[4]))
        payload = str(cmd[5])
        soft_exp = str(cmd[6])
        cur = self._hashes.get(key, {}).get("watermark")
        if cur is None or wm >= int(cur):
            self._hashes[key] = {
                "watermark": str(wm),
                "payload": payload,
                "soft_exp_ms": soft_exp,
            }
            return b":1\r\n"
        return b":0\r\n"

    def _handle_del(self, cmd: list[RespFrame]) -> bytes:
        removed = 0
        for key in cmd[1:]:
            if str(key) in self._hashes:
                del self._hashes[str(key)]
                removed += 1
        return f":{removed}\r\n".encode()

    def _handle_set(self, cmd: list[RespFrame]) -> bytes:
        lkey = str(cmd[1])
        if lkey in self._leases:
            return b"$-1\r\n"
        self._leases.add(lkey)
        return b"+OK\r\n"

    async def _serve_loop(
        self,
        incoming: asyncio.StreamReader,
        outgoing: asyncio.StreamReader,
    ) -> None:
        while not incoming.at_eof():
            try:
                cmd = await RespProtocolCodec.read_frame(incoming)
            except asyncio.IncompleteReadError:
                break
            if not isinstance(cmd, list) or not cmd:
                outgoing.feed_data(b"-ERR invalid frame\r\n")
                continue
            outgoing.feed_data(self._dispatch_command(cmd))


class _LoopbackStreamWriter:
    def __init__(
        self,
        peer_reader: asyncio.StreamReader,
        server_task: asyncio.Task[None],
    ) -> None:
        self._peer = peer_reader
        self._task = server_task
        self._closed = False

    def is_closing(self) -> bool:
        return self._closed

    def write(self, data: bytes) -> None:
        self._peer.feed_data(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def close(self) -> None:
        self._closed = True
        self._peer.feed_eof()
        self._task.cancel()

    async def wait_closed(self) -> None:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_resp_socket_store_executor_encodes_and_parses_wire_protocol() -> None:
    harness = _InMemoryRespPairHarness()
    executor = RespSocketStoreExecutor(
        host="valkey.internal",
        port=6379,
        pool_size=2,
        connection_factory=harness.open_connection,
    )

    miss_dto = await executor.read_projection_hash("proj:orders:missing")
    assert miss_dto.status == CacheStoreOperationStatus.OK
    assert miss_dto.payload_json is None

    cas1 = await executor.eval_cas_script(
        script=UPSERT_IF_NEWER_WATERMARK_LUA,
        storage_key="proj:orders:1",
        watermark=50,
        payload_json='{"id":"1"}',
        soft_expiry_epoch_ms=999999,
        hard_ttl_seconds=300,
    )
    assert cas1.status == CacheStoreOperationStatus.OK
    assert cas1.applied is True

    cas_stale = await executor.eval_cas_script(
        script=UPSERT_IF_NEWER_WATERMARK_LUA,
        storage_key="proj:orders:1",
        watermark=40,
        payload_json='{"id":"stale"}',
        soft_expiry_epoch_ms=999999,
        hard_ttl_seconds=300,
    )
    assert cas_stale.applied is False

    read_dto = await executor.read_projection_hash("proj:orders:1")
    assert read_dto.status == CacheStoreOperationStatus.OK
    assert read_dto.payload_json == '{"id":"1"}'
    assert read_dto.source_watermark == 50
    assert read_dto.soft_expiry_epoch_ms == 999999

    assert await executor.try_acquire_refresh_lease("lease:1", 2000) is True
    assert await executor.try_acquire_refresh_lease("lease:1", 2000) is False

    assert await executor.delete_storage_keys([]) == 0
    assert await executor.delete_storage_keys(["proj:orders:1"]) == 1
    await executor.close()


@pytest.mark.asyncio
async def test_resp_socket_store_executor_isolates_protocol_failures_gracefully() -> None:
    harness = _InMemoryRespPairHarness(fail_with_protocol_error=True)
    executor = RespSocketStoreExecutor(
        host="valkey.internal",
        port=6379,
        pool_size=1,
        connection_factory=harness.open_connection,
    )

    read_err = await executor.read_projection_hash("proj:1")
    assert read_err.status == CacheStoreOperationStatus.UNAVAILABLE

    cas_err = await executor.eval_cas_script(
        script=UPSERT_IF_NEWER_WATERMARK_LUA,
        storage_key="proj:1",
        watermark=1,
        payload_json="{}",
        soft_expiry_epoch_ms=1000,
        hard_ttl_seconds=10,
    )
    assert cas_err.status == CacheStoreOperationStatus.UNAVAILABLE
    assert cas_err.applied is False

    assert await executor.delete_storage_keys(["proj:1"]) == 0
    assert await executor.try_acquire_refresh_lease("lease:1", 1000) is False

    bad_reader = asyncio.StreamReader()
    bad_reader.feed_data(b"?invalid\r\n")
    with pytest.raises(RespProtocolError, match="Unexpected RESP frame prefix"):
        await RespProtocolCodec.read_frame(bad_reader)
