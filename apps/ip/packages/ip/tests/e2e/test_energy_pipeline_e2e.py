"""End-to-End Integration Test for the 5-Layer SEDA Pipeline (L1 -> L2 -> L3 -> L5) on PostgreSQL.

Verifies:
- L1 Ingest -> L2 Replica -> L3 Normalized + GEM + Canonical MDM -> L5 Outbound
- Unified end-to-end trace lineage (`trace_id`, `correlation_id`) across `ip_trace_events`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from database.types import GlobalSession, TenantSession
from ip.application.domains.energy.canonical import (
    CanonicalMeterReadingDTO,
    EnergyEntityType,
)
from ip.application.domains.energy.repository import SqlAlchemyEnergyDomainRepository
from ip.application.transformers.energy.itron_mdm import ItronMdmTransformer
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalized_record_repository import (
    SqlAlchemyNormalizedRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.outbound_record_repository import (
    SqlAlchemyOutboundRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.uow import (
    SqlAlchemyIpDataPlaneUnitOfWork,
)
from ip.engine.adapters.outbound.database.models.data_plane import IpTraceEventModel
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import (
    TieredStorageAdapter,
)
from ip.engine.application.use_cases.ingress.ingest_record_use_case import (
    IngestRecordCommand,
    IngestRecordUseCase,
)
from ip.engine.application.use_cases.replication.replicate_records_use_case import (
    ReplicateRecordsCommand,
    ReplicateRecordsUseCase,
)
from ip.engine.domain.enums import (
    AuthType,
    CursorKind,
    IpTraceEventType,
)
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import compute_record_key
from ip.engine.domain.models.stream_definition import StreamDefinition
from ip.engine.ports.outbound.transformer_hook_port import ReplicaSnapshotDTO
from seedwork.domain.types import JsonDict
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_full_l1_to_l5_energy_pipeline_vertical_slice_on_postgres(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    """Verifies L1 Ingest -> L2 Replica -> L3 Normalized + GEM + Canonical MDM -> L5 Outbound with unified trace_id."""
    # 0. Control Plane: Provision Connection
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="ERCOT Smart Grid Head-End",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://ercot.itron-ami.com"},
        encrypted_credentials=b"kid:k1:secret",
        endpoint_for_fingerprint="https://ercot.itron-ami.com",
    )
    await conn_repo.save(conn)

    # 1. Layer 1: Ingest raw webhook payload via IngestRecordUseCase
    uow = SqlAlchemyIpDataPlaneUnitOfWork(tenant_session)
    storage = TieredStorageAdapter()
    ingest_uc = IngestRecordUseCase(
        uow=uow,
        tiered_storage=storage,
    )

    raw_payload: JsonDict = {
        "meter_serial": "MTR-ERCOT-777",
        "service_point_id": "SP-ERCOT-777",
        "timestamp": "2026-10-22T12:00:00+00:00",
        "interval_minutes": 15,
        "kwh_delivered": 31.45,
        "kwh_received": 2.10,
        "voltage_avg": 240.2,
        "quality": "VALIDATED",
    }
    receipt = await ingest_uc.execute(
        IngestRecordCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            app_id="itron_mdm",
            stream_name="interval_reads",
            payload=raw_payload,
            headers={"Content-Type": "application/json"},
            correlation_id="CORR-ERCOT-777",
        )
    )
    assert receipt.status == "ACCEPTED"
    trace_id = receipt.trace_id

    # 2. Layer 2: Declarative Replication via ReplicateRecordsUseCase
    replicate_uc = ReplicateRecordsUseCase(uow=uow)
    stream_def = StreamDefinition(
        stream="interval_reads",
        primary_key=(("meter_serial",), ("timestamp",)),
        cursor_field=("timestamp",),
        cursor_kind=CursorKind.DATETIME,
    )
    rep_res = await replicate_uc.execute(
        ReplicateRecordsCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="interval_reads",
            inbound_record_id=receipt.record_id,
            generation_id=1,
            sync_id="sync_ercot_777",
            trace_id=trace_id,
            stream_definition=stream_def,
        )
    )
    assert rep_res.is_ok
    assert rep_res.value.inserted_count == 1

    replica_repo = SqlAlchemyReplicaRecordRepository(tenant_session)
    record_key = compute_record_key(("MTR-ERCOT-777", "2026-10-22T12:00:00+00:00"))
    replica = await replica_repo.get_by_key(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="interval_reads",
        record_key=record_key,
    )
    assert replica is not None

    # 3. Layer 3 & 4: Transform to NormalizedRecord + CanonicalMeterReadingDTO + GlobalEntityMap
    transformer = ItronMdmTransformer()
    replica_snapshot = ReplicaSnapshotDTO(
        stream=replica.stream,
        record_key=replica.record_key,
        data=replica.data,
        primary_key_values=replica.primary_key_values,
    )
    normalized_dto = transformer.normalize(replica_snapshot)
    assert normalized_dto is not None

    norm_repo = SqlAlchemyNormalizedRecordRepository(tenant_session)
    norm_record = NormalizedRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        canonical_type=normalized_dto.canonical_type,
        source_id=normalized_dto.source_id,
        canonical_data=normalized_dto.data,
        trace_id=trace_id,
        correlation_id="CORR-ERCOT-777",
    )
    await norm_repo.save(norm_record)

    now = datetime.now(UTC)
    reading_dto = CanonicalMeterReadingDTO(
        id="ip_mdmr_ercot_777",
        tenant_id=seeded_ip_tenant,
        trace_id=trace_id,
        correlation_id="CORR-ERCOT-777",
        source_connection_id=conn.id,
        source_replica_id=replica.id,
        meter_serial_number=str(normalized_dto.data["meter_serial_number"]),
        service_point_id=str(normalized_dto.data["service_point_id"]),
        reading_timestamp=now,
        interval_minutes=15,
        kwh_delivered=31.45,
        kwh_received=2.10,
        voltage_avg=240.2,
        quality_flag="VALIDATED",
        recorded_at=now,
    )
    energy_repo = SqlAlchemyEnergyDomainRepository(tenant_session)
    await energy_repo.save_meter_reading(reading_dto)

    gem_repo = SqlAlchemyGlobalEntityMapRepository(tenant_session)
    gem = GlobalEntityMap.create(
        tenant_id=seeded_ip_tenant,
        trace_id=trace_id,
        correlation_id="CORR-ERCOT-777",
        entity_domain=EnergyEntityType.MDM_METER_READING,
        canonical_id=reading_dto.id,
        source_connection_id=conn.id,
        source_entity_id=replica.record_key,
    )
    gem.bind_destination("ip_conn_erp", "SAP-DOC-777")
    await gem_repo.save(gem)

    # 4. Layer 5: Outbound Egress Record
    outbound_repo = SqlAlchemyOutboundRecordRepository(tenant_session)
    outbound = OutboundRecord.create_pending(
        tenant_id=seeded_ip_tenant,
        connection_id="ip_conn_erp",
        app_id="sap_s4hana",
        stream_name="meter_readings",
        target_url="https://sap.utility.com/api/readings",
        http_method="POST",
        payload_bytes=b'{"doc":"SAP-DOC-777"}',
        is_inlined=True,
        trace_id=trace_id,
        correlation_id="CORR-ERCOT-777",
        request_headers={"Content-Type": "application/json"},
        request_body={"doc": "SAP-DOC-777"},
    )
    outbound.mark_delivered(
        response_status_code=200,
        response_headers={"Content-Type": "application/json"},
        response_body={"sap_doc_id": "SAP-DOC-777"},
        duration_ms=42,
    )
    await outbound_repo.save(outbound)

    # 5. Assert unified end-to-end trace timeline in PostgreSQL `ip_trace_events`
    trace_stmt = (
        select(IpTraceEventModel)
        .where(
            IpTraceEventModel.tenant_id == seeded_ip_tenant,
            IpTraceEventModel.trace_id == trace_id,
        )
        .order_by(IpTraceEventModel.created_at.asc())
    )
    trace_events = (await tenant_session.execute(trace_stmt)).scalars().all()
    event_types = [t.event_type for t in trace_events]

    assert IpTraceEventType.L1_INGEST_RECEIVED.value in event_types
    assert IpTraceEventType.L2_REPLICA_CREATED.value in event_types
    assert IpTraceEventType.L3_NORMALIZED.value in event_types
    assert IpTraceEventType.L5_DISPATCH_PENDING.value in event_types
    assert IpTraceEventType.L5_DISPATCH_DELIVERED.value in event_types
