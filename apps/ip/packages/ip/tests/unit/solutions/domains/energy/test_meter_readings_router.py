"""Unit tests for Meter Reading Inspection HTTP Router (FastAPI)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from database.olap.adapters.in_memory_olap_adapter import InMemoryOlapAdapter
from fastapi import FastAPI
from helpers.worker_fakes import FakeDataPlaneUoW
from httpx import ASGITransport, AsyncClient
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_data_plane_uow_provider,
    get_olap_client,
    require_canonical_records_read,
)
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
from ip.solutions.domains.energy.router import router


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
def api_setup() -> tuple[FastAPI, FakeDataPlaneUoW, InMemoryOlapAdapter]:
    app = FastAPI()
    app.include_router(router)

    uow = FakeDataPlaneUoW()
    uow_provider = _FakeDataPlaneUoWProvider(uow)
    olap_client = InMemoryOlapAdapter()

    mock_identity = IdentityContext(
        subject="user_admin",
        claims={"sub": "user_admin"},
        tenant_id="ten_01",
        roles=("tenant_admin",),
    )

    app.dependency_overrides[get_ip_data_plane_uow_provider] = lambda: uow_provider
    app.dependency_overrides[get_olap_client] = lambda: olap_client
    app.dependency_overrides[require_canonical_records_read] = lambda: mock_identity

    return app, uow, olap_client


@pytest.mark.asyncio
async def test_search_meter_readings_endpoint(
    api_setup: tuple[FastAPI, FakeDataPlaneUoW, InMemoryOlapAdapter],
) -> None:
    app, _uow, olap = api_setup
    now = datetime.now(UTC)

    # Insert test readings in OLAP
    await olap.insert_batch(
        table="ip.meter_readings",
        records=[
            {
                "meter_serial_number": "MTR-1001",
                "tenant_id": "ten_01",
                "service_point_id": "SP-01",
                "interval_end_utc": now,
                "scaled_kwh_delivered": 12.5,
                "scaled_kwh_received": 0.0,
                "voltage_v": 240.0,
                "quality_status": "VALID",
                "batch_id": "batch_alpha",
            },
            {
                "meter_serial_number": "MTR-1001",
                "tenant_id": "ten_01",
                "service_point_id": "SP-01",
                "interval_end_utc": now,
                "scaled_kwh_delivered": 15.0,
                "scaled_kwh_received": 0.0,
                "voltage_v": 239.5,
                "quality_status": "VALID",
                "batch_id": "batch_alpha",
            },
            {
                "meter_serial_number": "MTR-2002",
                "tenant_id": "ten_01",
                "service_point_id": "SP-02",
                "interval_end_utc": now,
                "scaled_kwh_delivered": 5.0,
                "scaled_kwh_received": 0.0,
                "voltage_v": 120.0,
                "quality_status": "VALID",
                "batch_id": "batch_beta",
            },
        ],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Search specifically for MTR-1001
        res = await client.get(
            "/api/v1/tenants/ten_01/ip/meter-readings/search",
            params={"meter_serial_number": "MTR-1001", "limit": 10},
        )
        assert res.status_code == 200
        data = res.json()
        assert "summary" in data
        assert "readings" in data
        assert len(data["readings"]) == 2
        summary = data["summary"]
        assert summary["meter_serial_number"] == "MTR-1001"
        assert summary["tenant_id"] == "ten_01"
        assert summary["total_readings_24h"] == 2
        assert summary["total_kwh_delivered_24h"] == 27.5
        assert summary["active_quality_status"] == "VALID"


@pytest.mark.asyncio
async def test_batch_micro_sample_endpoint(
    api_setup: tuple[FastAPI, FakeDataPlaneUoW, InMemoryOlapAdapter],
) -> None:
    app, uow, olap = api_setup
    now = datetime.now(UTC)

    # Seed BatchManifest in PostgreSQL Data Plane UoW
    manifest = BatchManifest(
        id="batch_alpha",
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="app_hes",
        stream_name="meter_readings",
        priority_lane=PriorityLane.P1_LIVE,
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
        status=BatchManifestStatus.COMPLETED,
        l1_raw_uri="s3://bronze/batch_alpha.raw.zst",
        payload_sha256="abc123sha",
        payload_size_bytes=4096,
        window_start_utc=now,
        window_end_utc=now,
        raw_ingested_count=100,
        duplicates_dropped_count=0,
        valid_canonical_count=98,
        quarantined_held_count=2,
        promoted_outage_clusters_count=0,
        trace_id="trc_manifest_01",
        created_at=now,
    )
    await uow.batch_manifests.save(manifest)

    # Seed OLAP rows for this batch
    await olap.insert_batch(
        table="ip.meter_readings",
        records=[
            {
                "meter_serial_number": "MTR-1",
                "tenant_id": "ten_01",
                "batch_id": "batch_alpha",
                "interval_end_utc": now,
            },
            {
                "meter_serial_number": "MTR-2",
                "tenant_id": "ten_01",
                "batch_id": "batch_alpha",
                "interval_end_utc": now,
            },
        ],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/v1/tenants/ten_01/ip/meter-readings/batches/batch_alpha/micro-sample",
            params={"limit": 50},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["batch_id"] == "batch_alpha"
        assert data["tenant_id"] == "ten_01"
        assert data["total_count"] == 100
        assert data["valid_count"] == 98
        assert data["quarantined_count"] == 2
        assert len(data["micro_sample_records"]) == 2
