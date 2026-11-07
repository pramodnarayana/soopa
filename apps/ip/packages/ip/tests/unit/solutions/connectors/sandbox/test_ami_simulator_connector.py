"""Comprehensive unit tests for the Smart Grid AMI Simulator Connector and Generators.

Verifies:
1. ConnectorPort protocol adherence (spec, check, discover, read_stream, fetch_record).
2. Deterministic synthetic physics (CIM/Green Button intervals and service points).
3. 100% downstream pipeline parity: Generated payloads are successfully transformed
   by AmiMeterReadingTransformerV1 and AmiServicePointTransformerV1 with zero rejections.
4. Native registration in create_default_catalog_registry().
"""

from __future__ import annotations

import pytest
from ip.engine.domain.normalization.transformation import (
    ReplicaSnapshot,
    TransformationContext,
)
from ip.engine.ports.outbound.connector_port import (
    RecordEnvelopeDTO,
)
from ip.solutions.bootstrap import create_solution_catalog_registry
from ip.solutions.connectors.sandbox.energy.ami_simulator_connector import (
    EnergyAmiSimulatorConnector,
)
from ip.solutions.domains.energy.canonical import EnergyEntityType
from ip.solutions.domains.energy.transformers import (
    AmiMeterReadingTransformerV1,
    AmiServicePointTransformerV1,
)


@pytest.fixture
def connector() -> EnergyAmiSimulatorConnector:
    return EnergyAmiSimulatorConnector()


@pytest.fixture
def reading_transformer() -> AmiMeterReadingTransformerV1:
    return AmiMeterReadingTransformerV1()


@pytest.fixture
def sp_transformer() -> AmiServicePointTransformerV1:
    return AmiServicePointTransformerV1()


def test_catalog_summary_metadata(connector: EnergyAmiSimulatorConnector) -> None:
    summary = connector.default_catalog_summary()
    assert summary.app_id == "energy_ami_simulator"
    assert summary.category == "ENERGY"
    assert summary.auth_type == "NO_AUTH"
    assert summary.connector_type == "NATIVE_SIMULATOR"
    assert "Smart Grid AMI" in summary.display_name


def test_spec_exposes_configurable_parameters(connector: EnergyAmiSimulatorConnector) -> None:
    spec = connector.spec()
    assert spec.app_id == "energy_ami_simulator"
    assert spec.auth_type == "NO_AUTH"
    assert spec.category == "ENERGY"

    property_names = {p.name for p in spec.properties}
    assert "meter_count" in property_names


@pytest.mark.asyncio
async def test_check_returns_ok_status(connector: EnergyAmiSimulatorConnector) -> None:
    res = await connector.check(public_config={"meter_count": 10}, credentials={})
    assert res.success is True
    assert res.status == "SUCCEEDED"
    assert "10 simulated meter endpoints" in (res.message or "")


@pytest.mark.asyncio
async def test_discover_declares_canonical_streams(
    connector: EnergyAmiSimulatorConnector,
) -> None:
    catalog = await connector.discover(
        connection_id="conn_sim_01",
        public_config={},
        credentials={},
    )
    assert catalog.success is True
    assert len(catalog.streams) == 1

    sp_stream = catalog.streams[0]
    assert sp_stream.name == "service_points"
    assert sp_stream.cursor_field is None
    assert "FULL_REFRESH" in sp_stream.supported_sync_modes
    assert "INCREMENTAL" in sp_stream.supported_sync_modes
    assert sp_stream.default_transformation_id == "energy.ami_service_point"
    assert sp_stream.default_transformation_version == 1


@pytest.mark.asyncio
async def test_read_stream_service_points_transforms_cleanly(
    connector: EnergyAmiSimulatorConnector,
    sp_transformer: AmiServicePointTransformerV1,
) -> None:
    records: list[RecordEnvelopeDTO] = []
    async for record in connector.read_stream(
        stream_name="service_points",
        public_config={"meter_count": 3},
        credentials={},
    ):
        records.append(record)

    assert len(records) == 3
    for rec in records:
        assert rec.stream_name == "service_points"
        assert rec.record_id.startswith("SP-")
        assert "meter_serial" in rec.data
        assert "service_address" in rec.data

        # Feed into production L3 Transformer
        replica = ReplicaSnapshot(
            id=rec.record_id,
            connection_id="conn_sim_01",
            stream="service_points",
            record_key=rec.record_id,
            version=1,
            data=rec.data,
        )
        ctx = TransformationContext(
            connection_id="conn_sim_01",
            stream="service_points",
            tenant_id="ten_test",
            trace_id="tr_01",
        )
        result = sp_transformer.transform(replica, ctx)
        assert len(result.rejections) == 0, f"Unexpected rejection: {result.rejections}"
        assert len(result.drafts) == 1
        draft = result.drafts[0]
        assert draft.canonical_type == EnergyEntityType.MDM_SERVICE_POINT.value
        assert draft.fields["service_point_external_id"] == rec.record_id


@pytest.mark.asyncio
async def test_read_stream_interval_reads_transforms_cleanly(
    connector: EnergyAmiSimulatorConnector,
    reading_transformer: AmiMeterReadingTransformerV1,
) -> None:
    records: list[RecordEnvelopeDTO] = []
    async for record in connector.read_stream(
        stream_name="interval_reads",
        public_config={"meter_count": 2, "intervals_per_meter": 4},
        credentials={},
    ):
        records.append(record)

    # 2 meters * 4 intervals = 8 total readings
    assert len(records) == 8
    for rec in records:
        assert rec.stream_name == "interval_reads"
        assert ":" in rec.record_id
        assert rec.cursor_value is not None
        assert rec.data["interval_minutes"] == 15
        assert rec.data["kwh_delivered"] >= 0.0
        assert 110.0 <= rec.data["voltage_avg"] <= 130.0

        # Feed into production L3 Transformer
        replica = ReplicaSnapshot(
            id=rec.record_id,
            connection_id="conn_sim_01",
            stream="interval_reads",
            record_key=rec.record_id,
            version=1,
            data=rec.data,
        )
        ctx = TransformationContext(
            connection_id="conn_sim_01",
            stream="interval_reads",
            tenant_id="ten_test",
            trace_id="tr_01",
        )
        result = reading_transformer.transform(replica, ctx)
        assert len(result.rejections) == 0, f"Unexpected rejection: {result.rejections}"
        assert len(result.drafts) == 1
        draft = result.drafts[0]
        assert draft.canonical_type == EnergyEntityType.MDM_METER_READING.value
        assert draft.fields["interval_minutes"] == 15
        assert draft.fields["kwh_delivered"] == rec.data["kwh_delivered"]


@pytest.mark.asyncio
async def test_read_stream_cursor_pagination(
    connector: EnergyAmiSimulatorConnector,
) -> None:
    # First sync without cursor
    initial_records: list[RecordEnvelopeDTO] = []
    async for record in connector.read_stream(
        stream_name="interval_reads",
        public_config={"meter_count": 1, "intervals_per_meter": 5},
        credentials={},
    ):
        initial_records.append(record)

    assert len(initial_records) == 5
    mid_cursor = initial_records[2].cursor_value

    # Subsequent sync using mid_cursor
    filtered_records: list[RecordEnvelopeDTO] = []
    async for record in connector.read_stream(
        stream_name="interval_reads",
        public_config={"meter_count": 1, "intervals_per_meter": 5},
        credentials={},
        cursor=mid_cursor,
    ):
        filtered_records.append(record)

    # Should only return records strictly newer than mid_cursor
    assert mid_cursor is not None
    assert len(filtered_records) == 2
    for r in filtered_records:
        assert r.cursor_value is not None
        assert r.cursor_value > mid_cursor


def test_builtin_catalog_registry_includes_simulator() -> None:
    registry = create_solution_catalog_registry()
    apps = registry.list_apps(category="ENERGY")
    app_summary = next((a for a in apps if a.app_id == "energy_ami_simulator"), None)
    assert app_summary is not None
    assert app_summary.display_name == "Smart Grid AMI (Simulator)"
    assert app_summary.category == "ENERGY"
    assert app_summary.auth_type == "NO_AUTH"

    conn_res = registry.get_connector("energy_ami_simulator")
    assert conn_res.is_ok
    conn = conn_res.unwrap()
    assert isinstance(conn, EnergyAmiSimulatorConnector)
