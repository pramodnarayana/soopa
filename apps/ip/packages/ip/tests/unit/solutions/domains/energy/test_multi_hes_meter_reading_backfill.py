"""Unit tests for the Multi-HES Meter Reading Backfill Stitch (Zero Mocks).

Verifies proper decoupling between Itron, Siemens, and Landis+Gyr fetchers/normalizers,
and validates that the Stitch cleanly sews them together across temporal slices.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ip.sdk import RequestSpec, StitchContext, TimeSlice
from ip.solutions.domains.energy.itron import (
    fetch_itron_meter_readings,
    normalize_itron_meter_reading,
)
from ip.solutions.domains.energy.landis import (
    fetch_landis_meter_readings,
    normalize_landis_meter_reading,
)
from ip.solutions.domains.energy.siemens import (
    fetch_siemens_meter_readings,
    normalize_siemens_meter_reading,
)
from ip.solutions.domains.energy.stitches.backfill import (
    MULTI_HES_BACKFILL_STITCH,
    HesBackfillCommand,
    execute_multi_hes_backfill,
    resolve_hes_fetcher,
    resolve_hes_normalizer,
)
from seedwork.domain.types import JsonDict


class FakeStitchHttp:
    """Pure in-memory test fake for StitchHttpPort capturing dispatched requests."""

    def __init__(self) -> None:
        self.dispatched_specs: list[tuple[str, RequestSpec]] = []
        self.dispatched_calls: list[tuple[str, str, JsonDict]] = []

    async def dispatch_spec(self, *, connection_id: str, spec: RequestSpec) -> JsonDict:
        self.dispatched_specs.append((connection_id, spec))
        return {
            "status": "SUBMITTED",
            "job_id": f"job_{connection_id}_{spec.path.split('/')[-1]}",
        }

    async def dispatch(
        self,
        *,
        connection_id: str,
        endpoint: str,
        payload: JsonDict,
        method: str = "POST",
        headers: dict[str, str] | None = None,
    ) -> JsonDict:
        self.dispatched_calls.append((connection_id, endpoint, payload))
        return {"status": "SUBMITTED", "job_id": f"job_{connection_id}_fallback"}


class FakeTimeSlicer:
    """Pure test fake generating predictable 1-day temporal slices."""

    def slice_daily(self, start_date: datetime, end_date: datetime) -> tuple[TimeSlice, ...]:
        return (
            TimeSlice(
                start=start_date,
                end=end_date,
            ),
        )


class FakeKafka:
    async def publish(
        self, *, topic: str, partition_key: str, payload: JsonDict, **kwargs: object
    ) -> None:
        pass


class FakeReplica:
    async def get_by_key(
        self, *, connection_id: str, stream: str, record_key: str
    ) -> JsonDict | None:
        return None


def test_resolve_hes_fetcher_resolves_decoupled_vendor_functions() -> None:
    assert resolve_hes_fetcher("conn_itron_hes") is fetch_itron_meter_readings
    assert resolve_hes_fetcher("itron_openway") is fetch_itron_meter_readings
    assert resolve_hes_fetcher("conn_siemens_hes") is fetch_siemens_meter_readings
    assert resolve_hes_fetcher("siemens_energyip") is fetch_siemens_meter_readings
    assert resolve_hes_fetcher("conn_landis_hes") is fetch_landis_meter_readings
    assert resolve_hes_fetcher("landis_gridstream") is fetch_landis_meter_readings


def test_resolve_hes_fetcher_rejects_unknown_vendor() -> None:
    with pytest.raises(ValueError, match="Unsupported HES target connection"):
        resolve_hes_fetcher("unknown_hes_vendor")


def test_resolve_hes_normalizer_resolves_decoupled_normalizers() -> None:
    assert resolve_hes_normalizer("itron") is normalize_itron_meter_reading
    assert resolve_hes_normalizer("siemens") is normalize_siemens_meter_reading
    assert resolve_hes_normalizer("landis") is normalize_landis_meter_reading


def test_resolve_hes_normalizer_rejects_unknown_vendor() -> None:
    with pytest.raises(ValueError, match="Unsupported HES normalizer target"):
        resolve_hes_normalizer("unknown_vendor")


@pytest.mark.asyncio
async def test_execute_multi_hes_backfill_stitches_itron_siemens_landis() -> None:
    fake_http = FakeStitchHttp()
    ctx = StitchContext(
        tenant_id="bescom_power",
        trace_id="trace_backfill_001",
        now=datetime.now(UTC),
        http=fake_http,
        slicer=FakeTimeSlicer(),
        kafka=FakeKafka(),
        replica=FakeReplica(),
    )

    cmd = HesBackfillCommand(
        tenant_id="bescom_power",
        correlation_id="corr_backfill_test",
        start_time="2026-10-01T00:00:00Z",
        end_time="2026-10-02T00:00:00Z",
        meter_serials=("MTR-100", "MTR-200"),
        hes_targets=("conn_itron_hes", "conn_siemens_hes", "conn_landis_hes"),
    )

    result = await execute_multi_hes_backfill(ctx, cmd)

    # 1. Assert result metadata
    assert result.correlation_id == "corr_backfill_test"
    assert result.total_slices == 1
    assert len(result.dispatched_jobs) == 3

    # 2. Verify Itron job: Dispatched to Itron SOAP endpoint
    itron_job = result.dispatched_jobs[0]
    assert itron_job.hes_target == "conn_itron_hes"
    assert itron_job.request_path == "/AsynchronousCollection/v1/Extract"
    assert itron_job.request_method == "POST"

    # 3. Verify Siemens job: Dispatched to Siemens EnergyIP REST endpoint
    siemens_job = result.dispatched_jobs[1]
    assert siemens_job.hes_target == "conn_siemens_hes"
    assert siemens_job.request_path == "/energyip/api/v1/meter-readings/intervals"
    assert siemens_job.request_method == "POST"

    # 4. Verify Landis job: Dispatched to Landis Gridstream REST endpoint
    landis_job = result.dispatched_jobs[2]
    assert landis_job.hes_target == "conn_landis_hes"
    assert landis_job.request_path == "/api/v2/meter-readings/query"
    assert landis_job.request_method == "POST"

    # 5. Verify the HTTP port received exact vendor RequestSpecs
    assert len(fake_http.dispatched_specs) == 3

    itron_conn, itron_spec = fake_http.dispatched_specs[0]
    assert itron_conn == "conn_itron_hes"
    assert "ExtractIntervalData" in itron_spec.headers["SOAPAction"]
    assert isinstance(itron_spec.body, str)
    assert "<DeviceID>MTR-100</DeviceID>" in itron_spec.body

    siemens_conn, siemens_spec = fake_http.dispatched_specs[1]
    assert siemens_conn == "conn_siemens_hes"
    assert siemens_spec.headers["X-EnergyIP-Version"] == "v1"
    assert isinstance(siemens_spec.body, dict)
    assert siemens_spec.body["meterIdentifiers"] == ["MTR-100", "MTR-200"]

    landis_conn, landis_spec = fake_http.dispatched_specs[2]
    assert landis_conn == "conn_landis_hes"
    assert landis_spec.headers["X-API-Version"] == "v2"
    assert isinstance(landis_spec.body, dict)
    assert landis_spec.body["meterList"] == ["MTR-100", "MTR-200"]


def test_stitch_spec_definition() -> None:
    assert MULTI_HES_BACKFILL_STITCH.id == "energy.multi_hes_meter_reading_backfill"
    assert MULTI_HES_BACKFILL_STITCH.trigger == "command.hes.meter_reading_backfill"
    assert MULTI_HES_BACKFILL_STITCH.handler is execute_multi_hes_backfill
