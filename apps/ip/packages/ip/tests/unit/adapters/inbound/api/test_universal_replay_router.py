"""Unit tests for Universal Replay HTTP Router (FastAPI)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterable, AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from helpers.worker_fakes import FakeDataPlaneUoW
from httpx import ASGITransport, AsyncClient
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_data_plane_uow_provider,
    get_payload_storage,
    require_flows_write,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.routers.universal_replay_router import router
from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.domain.intervals.enums import (
    BatchManifestStatus,
    IntervalPayloadFormat,
    PriorityLane,
)
from ip.engine.domain.intervals.models import BatchManifest
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from replay.domain.enums import ReplayStatus, ReplayTargetType
from storage.domain.enums import CompressionCodec
from storage.ports.payload_storage_port import PayloadStoragePort


class _FakePayloadStorage(PayloadStoragePort):
    def __init__(self, data: bytes = b'{"records": [1, 2, 3]}') -> None:
        self._data = data

    async def upload(self, tenant_id: str, message_id: str, payload: bytes) -> str:
        return f"s3://bucket/{tenant_id}/{message_id}"

    async def upload_partitioned(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        payload: bytes,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        return f"s3://bucket/{tenant_id}/{stream_name}/{batch_id}.{extension}"

    async def upload_stream(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        stream: AsyncIterable[bytes],
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
        content_type: str = "application/octet-stream",
    ) -> str:
        return f"s3://bucket/{tenant_id}/{stream_name}/{batch_id}.{extension}"

    async def download(self, storage_uri: str, decompress: bool = True) -> bytes | None:
        return self._data

    async def download_stream(self, storage_uri: str) -> AsyncIterable[bytes]:
        yield self._data

    async def generate_presigned_url(
        self,
        storage_uri: str,
        expiry_seconds: int = 3600,
        response_headers: dict[str, str] | None = None,
    ) -> str:
        return f"https://example.com/download/{storage_uri}"

    def build_partitioned_key(
        self,
        tenant_id: str,
        stream_name: str,
        batch_id: str,
        extension: str = "raw",
        compression: CompressionCodec = CompressionCodec.NONE,
    ) -> str:
        return f"tenants/{tenant_id}/{stream_name}/{batch_id}.{extension}"


class _FakeDataPlaneUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(self, uow: FakeDataPlaneUoW) -> None:
        self.uow = uow

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        return Result.ok(("shard_01", "sqlite+aiosqlite:///:memory:"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, shard_id: str, shard_dsn: str
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        yield self.uow


@pytest.fixture
def replay_api_setup() -> tuple[FastAPI, FakeDataPlaneUoW, _FakePayloadStorage]:
    app = FastAPI()
    app.include_router(router)

    uow = FakeDataPlaneUoW()
    uow_provider = _FakeDataPlaneUoWProvider(uow)
    storage = _FakePayloadStorage()

    mock_identity = IdentityContext(
        subject="user_operator",
        claims={"sub": "user_operator"},
        tenant_id="ten_01",
        roles=("tenant_admin",),
    )

    app.dependency_overrides[get_ip_data_plane_uow_provider] = lambda: uow_provider
    app.dependency_overrides[get_payload_storage] = lambda: storage
    app.dependency_overrides[require_tenant_member] = lambda: mock_identity
    app.dependency_overrides[require_flows_write] = lambda: mock_identity

    return app, uow, storage


@pytest.mark.asyncio
async def test_universal_replay_preview_endpoint(
    replay_api_setup: tuple[FastAPI, FakeDataPlaneUoW, _FakePayloadStorage],
) -> None:
    app, uow, _storage = replay_api_setup
    now = datetime.now(UTC)

    # Seed BatchManifest
    manifest = BatchManifest(
        id="batch_preview_01",
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="app_crm",
        stream_name="telemetry_events",
        priority_lane=PriorityLane.P1_LIVE,
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
        status=BatchManifestStatus.COMPLETED,
        l1_raw_uri="s3://bronze/batch_preview_01.raw.zst",
        payload_sha256="preview_sha",
        payload_size_bytes=1024,
        window_start_utc=now,
        window_end_utc=now,
        raw_ingested_count=250,
        duplicates_dropped_count=0,
        valid_canonical_count=250,
        quarantined_held_count=0,
        promoted_outage_clusters_count=0,
        trace_id="trc_manifest_prev",
        created_at=now,
    )
    await uow.batch_manifests.save(manifest)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Successful preview
        res = await client.post(
            "/api/v1/tenants/ten_01/ip/replay/preview",
            json={
                "target_id": "batch_preview_01",
                "target_type": "BATCH",
                "target_stage": "STAGE_1_RAW_INGRESS",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["target_id"] == "batch_preview_01"
        assert data["target_type"] == "BATCH"
        assert data["target_stage"] == "STAGE_1_RAW_INGRESS"
        assert data["total_record_count"] == 250
        assert data["will_deliver_to_egress"] is True
        assert data["requires_idempotency_key"] is True

        # 2. Invalid stage
        bad_res = await client.post(
            "/api/v1/tenants/ten_01/ip/replay/preview",
            json={
                "target_id": "batch_preview_01",
                "target_type": "BATCH",
                "target_stage": "INVALID_STAGE_XYZ",
            },
        )
        assert bad_res.status_code == 400


@pytest.mark.asyncio
async def test_universal_replay_execute_endpoint(
    replay_api_setup: tuple[FastAPI, FakeDataPlaneUoW, _FakePayloadStorage],
) -> None:
    app, uow, _storage = replay_api_setup
    now = datetime.now(UTC)

    manifest = BatchManifest(
        id="batch_exec_01",
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="app_crm",
        stream_name="telemetry_events",
        priority_lane=PriorityLane.P1_LIVE,
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
        status=BatchManifestStatus.COMPLETED,
        l1_raw_uri="s3://bronze/batch_exec_01.raw.zst",
        payload_sha256="exec_sha",
        payload_size_bytes=2048,
        window_start_utc=now,
        window_end_utc=now,
        raw_ingested_count=100,
        duplicates_dropped_count=0,
        valid_canonical_count=100,
        quarantined_held_count=0,
        promoted_outage_clusters_count=0,
        trace_id="trc_manifest_exec",
        created_at=now,
    )
    await uow.batch_manifests.save(manifest)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First execution
        res = await client.post(
            "/api/v1/tenants/ten_01/ip/replay/execute",
            json={
                "target_id": "batch_exec_01",
                "target_type": "BATCH",
                "target_stage": "STAGE_1_RAW_INGRESS",
                "reason": "Data correction due to sensor recalibration",
                "idempotency_key": "token_abc_123",
                "payload_override": {"calibration_factor": 1.05},
            },
        )
        assert res.status_code == 202
        data = res.json()
        assert data["target_id"] == "batch_exec_01"
        assert data["target_type"] == "BATCH"
        assert data["target_stage"] == "STAGE_1_RAW_INGRESS"
        assert data["status"] == "IN_FLIGHT"
        assert "replay_id" in data
        assert "trace_id" in data
        first_replay_id = data["replay_id"]

        # Verify audit ledger in uow.replay_ledger
        audits = await uow.replay_ledger.list_by_target(
            "ten_01", ReplayTargetType.BATCH, "batch_exec_01"
        )
        assert len(audits) >= 1
        assert audits[0].target_id == "batch_exec_01"
        assert audits[0].target_type == ReplayTargetType.BATCH
        assert audits[0].actor == "user_operator"
        assert audits[0].idempotency_key == "token_abc_123"
        assert audits[0].payload_override == {"calibration_factor": 1.05}
        assert audits[0].reason == "Data correction due to sensor recalibration"
        assert audits[0].status in (ReplayStatus.IN_FLIGHT, ReplayStatus.COMPLETED)

        # Idempotent retry: exact same request returns identical replay_id without duplicate execution
        retry_res = await client.post(
            "/api/v1/tenants/ten_01/ip/replay/execute",
            json={
                "target_id": "batch_exec_01",
                "target_type": "BATCH",
                "target_stage": "STAGE_1_RAW_INGRESS",
                "reason": "Data correction due to sensor recalibration",
                "idempotency_key": "token_abc_123",
                "payload_override": {"calibration_factor": 1.05},
            },
        )
        assert retry_res.status_code == 202
        retry_data = retry_res.json()
        assert retry_data["replay_id"] == first_replay_id
        # Confirm no extra records added to ledger
        all_audits = await uow.replay_ledger.list_by_target(
            "ten_01", ReplayTargetType.BATCH, "batch_exec_01"
        )
        assert len(all_audits) == 1
