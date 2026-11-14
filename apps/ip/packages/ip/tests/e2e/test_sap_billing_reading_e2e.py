"""End-to-End Integration Test for SAP Billing Readings Pipeline (L1 -> L2 -> L3 -> L4 Canonical) on PostgreSQL.

Verifies:
- L1 Ingest (SAP S/4HANA / SAP Billing payload)
- L2 Declarative Replication into replica_records
- L3 Normalization via SapBillingReadingTransformer into NormalizedRecord
- L4 Canonical MDM Persistence into mdm_billing_readings via SqlAlchemyBillingReadingCanonicalWriter & SqlAlchemyEnergyDomainRepository
- L4 -> L3 Projection via SqlAlchemyBillingReadingCanonicalReader (the exact query contract used by UI NormalizedEntityDataTable)
- Unified trace lineage across ip_trace_events
"""

from __future__ import annotations

import pytest
from database.types import GlobalSession, TenantSession
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalized_record_repository import (
    SqlAlchemyNormalizedRecordRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
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
from ip.engine.bootstrap.container import create_ip_data_plane_uow
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.domain.normalization.transformation import (
    CanonicalDataDict,
    ReplicaSnapshot,
    TransformationContext,
)
from ip.engine.domain.replication.enums import CursorKind
from ip.engine.domain.replication.replica_record import compute_record_key
from ip.engine.domain.replication.stream_definition import StreamDefinition
from ip.engine.domain.trace.enums import IpTraceEventType
from ip.solutions.domains.energy.canonical import (
    EnergyEntityType,
)
from ip.solutions.domains.energy.readers import SqlAlchemyBillingReadingCanonicalReader
from ip.solutions.domains.energy.repository import SqlAlchemyEnergyDomainRepository
from ip.solutions.domains.energy.transformers.sap.billing_reading import (
    SapBillingReadingTransformer,
)
from ip.solutions.domains.energy.writers import SqlAlchemyBillingReadingCanonicalWriter
from seedwork.domain.types import JsonDict
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_sap_billing_readings_pipeline_e2e_on_postgres(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    """Verifies end-to-end flow from SAP Billing ingress to canonical mdm_billing_readings and UI projection."""
    # 0. Control Plane: Provision Connection for SAP Billing
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="sap_s4hana",
        name="SAP IS-U Billing Engine",
        auth_type=AuthType.OAUTH2,
        public_config={"endpoint_url": "https://sap.utility-corp.com"},
        encrypted_credentials=b"kid:k1:sap_secret",
        endpoint_for_fingerprint="https://sap.utility-corp.com",
    )
    await conn_repo.save(conn)

    # 1. Layer 1: Ingest raw SAP billing reading payload via IngestRecordUseCase
    uow = create_ip_data_plane_uow(tenant_session)
    storage = TieredStorageAdapter()
    ingest_uc = IngestRecordUseCase(
        uow=uow,
        tiered_storage=storage,
    )

    raw_payload: JsonDict = {
        "reading_id": "BILL-SAP-99901",
        "meter_serial": "MTR-SAP-999",
        "service_point_id": "SP-SAP-999",
        "reading_timestamp": "2026-11-13T10:00:00+00:00",
        "kwh_delivered": 450.75,
        "quality": "VALIDATED",
    }
    receipt = await ingest_uc.execute(
        IngestRecordCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            app_id="sap_s4hana",
            stream_name="billing_readings",
            payload=raw_payload,
            headers={"Content-Type": "application/json"},
            correlation_id="CORR-SAP-BILLING-99901",
        )
    )
    assert receipt.status == "ACCEPTED"
    trace_id = receipt.trace_id

    # 2. Layer 2: Declarative Replication via ReplicateRecordsUseCase
    replicate_uc = ReplicateRecordsUseCase(uow=uow)
    stream_def = StreamDefinition(
        stream="billing_readings",
        primary_key=(("reading_id",), ("reading_timestamp",)),
        cursor_field=("reading_timestamp",),
        cursor_kind=CursorKind.DATETIME,
    )
    rep_res = await replicate_uc.execute(
        ReplicateRecordsCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="billing_readings",
            inbound_record_id=receipt.record_id,
            generation_id=1,
            sync_id="sync_sap_billing_99901",
            trace_id=trace_id,
            stream_definition=stream_def,
        )
    )
    assert rep_res.is_ok
    assert rep_res.value is not None
    assert rep_res.value.inserted_count == 1

    replica_repo = SqlAlchemyReplicaRecordRepository(tenant_session)
    record_key = compute_record_key(("BILL-SAP-99901", "2026-11-13T10:00:00+00:00"))
    replica = await replica_repo.get_by_key(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="billing_readings",
        record_key=record_key,
    )
    assert replica is not None
    assert replica.data["reading_id"] == "BILL-SAP-99901"
    assert replica.data["meter_serial"] == "MTR-SAP-999"

    # 3. Layer 3: Transform replica to NormalizedRecord using SapBillingReadingTransformer
    transformer = SapBillingReadingTransformer()
    replica_snapshot = ReplicaSnapshot(
        id=replica.id,
        connection_id=conn.id,
        stream=replica.stream,
        record_key=replica.record_key,
        version=replica.version,
        data=replica.data,
    )
    ctx = TransformationContext(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream=replica.stream,
        trace_id=trace_id,
        correlation_id="CORR-SAP-BILLING-99901",
    )
    transform_res = transformer.transform(replica_snapshot, ctx)
    assert len(transform_res.drafts) == 1
    assert len(transform_res.rejections) == 0

    draft = transform_res.drafts[0]
    assert draft.canonical_type == EnergyEntityType.MDM_BILLING_READING.value
    assert draft.fields["reading_id"] == "BILL-SAP-99901"
    assert draft.fields["meter_serial_number"] == "MTR-SAP-999"
    assert draft.fields["service_point_id"] == "SP-SAP-999"
    assert draft.fields["kwh_delivered"] == 450.75
    assert draft.fields["quality_flag"] == "VALIDATED"

    # Save NormalizedRecord
    norm_repo = SqlAlchemyNormalizedRecordRepository(tenant_session)
    canonical_data: CanonicalDataDict = {k: v for k, v in draft.fields.items()}
    norm_record = NormalizedRecord.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        canonical_type=draft.canonical_type,
        source_id=draft.source_id,
        canonical_data=canonical_data,
        trace_id=trace_id,
        correlation_id="CORR-SAP-BILLING-99901",
    )
    await norm_repo.save(norm_record)

    # 4. Layer 4: Write to Canonical MDM Table (mdm_billing_readings)
    canonical_writer = SqlAlchemyBillingReadingCanonicalWriter(
        repo_factory=lambda _: SqlAlchemyEnergyDomainRepository(tenant_session)
    )
    await canonical_writer.upsert(
        uow=uow,
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        source_id=draft.source_id,
        fields=draft.fields,
        extensions={},
        trace_id=trace_id,
        transformation_id="energy.sap_billing_reading",
        transformation_version=1,
        replica_id=replica.id,
        replica_version=replica.version,
        correlation_id="CORR-SAP-BILLING-99901",
    )

    # Verify retrieval from canonical domain repository
    energy_repo = SqlAlchemyEnergyDomainRepository(tenant_session)
    canonical_reading = await energy_repo.get_billing_reading_by_reading_id(
        tenant_id=seeded_ip_tenant,
        reading_id="BILL-SAP-99901",
    )
    assert canonical_reading is not None
    assert canonical_reading.reading_id == "BILL-SAP-99901"
    assert canonical_reading.meter_serial_number == "MTR-SAP-999"
    assert canonical_reading.service_point_id == "SP-SAP-999"
    assert canonical_reading.kwh_delivered == 450.75
    assert canonical_reading.quality_flag == "VALIDATED"
    assert canonical_reading.trace_id == trace_id

    # Verify list by meter serial number
    meter_readings = await energy_repo.list_billing_readings_by_meter(
        tenant_id=seeded_ip_tenant,
        meter_serial_number="MTR-SAP-999",
    )
    assert len(meter_readings) == 1
    assert meter_readings[0].reading_id == "BILL-SAP-99901"

    # 5. Layer 4 -> Layer 3 Projection: Canonical Reader (Used by UI Entities View)
    canonical_reader = SqlAlchemyBillingReadingCanonicalReader()
    projected_record = await canonical_reader.get_by_id(
        tenant_session,
        tenant_id=seeded_ip_tenant,
        record_id=canonical_reading.id,
    )
    assert projected_record is not None
    assert projected_record.canonical_type == EnergyEntityType.MDM_BILLING_READING.value
    assert projected_record.source_id == "BILL-SAP-99901"
    assert projected_record.canonical_data["reading_id"] == "BILL-SAP-99901"
    assert projected_record.canonical_data["meter_serial_number"] == "MTR-SAP-999"
    assert projected_record.canonical_data["kwh_delivered"] == 450.75
    assert projected_record.canonical_data["quality_flag"] == "VALIDATED"

    # Test list_records projection
    stream_records = await canonical_reader.list_records(
        tenant_session,
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        limit=10,
        offset=0,
    )
    assert len(stream_records) >= 1
    assert any(r.source_id == "BILL-SAP-99901" for r in stream_records)

    # 6. Verify GEM (Global Entity Map)
    gem_repo = SqlAlchemyGlobalEntityMapRepository(tenant_session)
    gem = await gem_repo.get_by_source(
        tenant_id=seeded_ip_tenant,
        entity_domain=EnergyEntityType.MDM_BILLING_READING.value,
        source_connection_id=conn.id,
        source_entity_id=draft.source_id,
    )
    assert gem is not None
    assert gem.canonical_id == canonical_reading.id

    # 7. Assert unified end-to-end trace timeline in PostgreSQL ip_trace_events
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

    assert IpTraceEventType.INGEST_RECEIVED.value in event_types
    assert IpTraceEventType.REPLICA_CREATED.value in event_types
