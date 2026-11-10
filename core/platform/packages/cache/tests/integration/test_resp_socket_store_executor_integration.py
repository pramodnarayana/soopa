from __future__ import annotations

import asyncio

import pytest

from cache.adapters.outbound.monotonic_cas_projection_adapter import (
    MonotonicCasProjectionAdapter,
)
from cache.adapters.outbound.resp_socket_store_executor import (
    RespFrame,
    RespProtocolCodec,
    RespSocketStoreExecutor,
)
from cache.domain.constants import CacheLookupStatus, CacheUpsertStatus
from cache.domain.projection import StampedProjectionDTO

pytestmark = pytest.mark.integration


class _LiveTcpRespServer:
    """Real OS loopback TCP server speaking binary RESP2 for Narrow Integration Tests."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._leases: set[str] = set()
        self._server: asyncio.Server | None = None
        self.port: int = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            host="127.0.0.1",
            port=0,
        )
        sockets = self._server.sockets
        if not sockets:
            raise RuntimeError("TCP server failed to bind ephemeral port")
        self.port = int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def _handle_hmget(self, cmd: list[RespFrame]) -> bytes:
        key = str(cmd[1])
        fields = [str(f) for f in cmd[2:]]
        stored = self._hashes.get(key, {})
        out = [f"*{len(fields)}\r\n".encode()]
        for f in fields:
            val = stored.get(f)
            if val is None:
                out.append(b"$-1\r\n")
            else:
                raw = val.encode("utf-8")
                out.append(f"${len(raw)}\r\n".encode() + raw + b"\r\n")
        return b"".join(out)

    def _handle_eval(self, cmd: list[RespFrame]) -> bytes:
        key = str(cmd[3])
        wm = int(str(cmd[4]))
        cur = self._hashes.get(key, {}).get("watermark")
        if cur is None or wm > int(cur):
            self._hashes[key] = {
                "watermark": str(wm),
                "payload": str(cmd[5]),
                "soft_exp_ms": str(cmd[6]),
            }
            return b":1\r\n"
        return b":0\r\n"

    def _execute(self, cmd: list[RespFrame]) -> bytes:
        verb = str(cmd[0]).upper()
        if verb == "HMGET":
            return self._handle_hmget(cmd)
        if verb == "EVAL":
            return self._handle_eval(cmd)
        if verb == "DEL":
            removed = sum(1 for k in cmd[1:] if self._hashes.pop(str(k), None) is not None)
            return f":{removed}\r\n".encode()
        if verb == "SET":
            lkey = str(cmd[1])
            if lkey in self._leases:
                return b"$-1\r\n"
            self._leases.add(lkey)
            return b"+OK\r\n"
        return b"-ERR unsupported\r\n"

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            while not reader.at_eof():
                cmd = await RespProtocolCodec.read_frame(reader)
                if not isinstance(cmd, list) or not cmd:
                    break
                writer.write(self._execute(cmd))
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()


@pytest.mark.integration
async def test_resp_socket_executor_and_cas_adapter_over_live_tcp_socket() -> None:
    server = _LiveTcpRespServer()
    await server.start()
    executor = RespSocketStoreExecutor(
        host="127.0.0.1",
        port=server.port,
        pool_size=4,
        timeout_seconds=1.0,
    )
    adapter = MonotonicCasProjectionAdapter(store_executor=executor)

    try:
        res_new = await adapter.upsert_projection_monotonic(
            namespace="consumer_profile",
            tenant_id="iam_ten_b2c",
            projection_key="usr_live_01",
            projection=StampedProjectionDTO(
                payload_json='{"tier":"gold"}',
                source_watermark=500,
            ),
            soft_ttl_seconds=60,
            hard_ttl_seconds=300,
        )
        assert res_new.status == CacheUpsertStatus.APPLIED

        res_stale = await adapter.upsert_projection_monotonic(
            namespace="consumer_profile",
            tenant_id="iam_ten_b2c",
            projection_key="usr_live_01",
            projection=StampedProjectionDTO(
                payload_json='{"tier":"silver"}',
                source_watermark=450,
            ),
            soft_ttl_seconds=60,
            hard_ttl_seconds=300,
        )
        assert res_stale.status == CacheUpsertStatus.SKIPPED_STALE_WATERMARK

        fetched = await adapter.get_projection(
            namespace="consumer_profile",
            tenant_id="iam_ten_b2c",
            projection_key="usr_live_01",
        )
        assert fetched.status == CacheLookupStatus.HIT_FRESH
        assert fetched.projection is not None
        assert fetched.projection.payload_json == '{"tier":"gold"}'
    finally:
        await executor.close()
        await server.stop()
