"""End-to-End Integration Test for the 5-Layer TMS Pipeline (L1 -> L2 -> L3 -> L5) on PostgreSQL.

Verifies:
- L1 Ingest -> L2 Replica -> L3 Normalized + GEM + Canonical TMS Load -> L5 Outbound
- Unified end-to-end trace lineage (`trace_id`, `correlation_id`) across `ip_trace_events`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from database.types import GlobalSession, TenantSession
from ip.application.domains.tms.canonical import (
    CanonicalLoadDTO,
    TmsEntityType,
)
from ip.application.domains.tms.repository import SqlAlchemyTmsDomainRepository
from ip.application.transformers.tms.mercury_gate import MercuryGateTransformer
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

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_full_l1_to_l5_tms_pipeline_vertical_slice_on_postgres(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    """Verifies L1 Ingest -> L2 Replica -> L3 Normalized + GEM + Canonical TMS -> L5 Outbound with unified trace_id."""
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="mercury_gate",
        name="MercuryGate TMS Gateway",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.mercurygate.com"},
        encrypted_credentials=b"kid:k1:secret",
        endpoint_for_fingerprint="https://api.mercurygate.com",
    )
    await conn_repo.save(conn)

    uow = SqlAlchemyIpDataPlaneUnitOfWork(tenant_session)
    storage = TieredStorageAdapter()
    ingest_uc = IngestRecordUseCase(uow=uow, tiered_storage=storage)

    raw_payload: JsonDict = {
        "reference_number": "LD-2026-8800",
        "carrier_scac": "JBHT",
        "origin_city": "Dallas",
        "origin_state": "TX",
        "destination_city": "Atlanta",
        "destination_state": "GA",
        "status": "IN_TRANSIT",
        "total_weight_lbs": 41200.0,
        "freight_charge_usd": 2950.0,
    }
    receipt = await ingest_uc.execute(
        IngestRecordCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            app_id="mercury_gate",
            stream_name="loads",
            payload=raw_payload,
            headers={"Content-Type": "application/json"},
            correlation_id="CORR-TMS-8800",
        )
    )
    assert receipt.status == "ACCEPTED"
    trace_id = receipt.trace_id

    replicate_uc = ReplicateRecordsUseCase(uow=uow)
    stream_def = StreamDefinition(
        stream="loads",
        primary_key=(("reference_number",),),
    )
    rep_res = await replicate_uc.execute(
        ReplicateRecordsCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="loads",
            inbound_record_id=receipt.record_id,
            generation_id=1,
            sync_id="sync_tms_8800",
            trace_id=trace_id,
            stream_definition=stream_def,
        )
    )
    assert rep_res.is_ok
    assert rep_res.value.inserted_count == 1

    replica_repo = SqlAlchemyReplicaRecordRepository(tenant_session)
    replica = await replica_repo.get_by_key(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="loads",
        record_key=compute_record_key(("LD-2026-8800",)),
    )
    assert replica is not None

    transformer = MercuryGateTransformer()
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
        correlation_id="CORR-TMS-8800",
    )
    await norm_repo.save(norm_record)

    now = datetime.now(UTC)
    load_dto = CanonicalLoadDTO(
        id="ip_tmsl_8800",
        tenant_id=seeded_ip_tenant,
        trace_id=trace_id,
        correlation_id="CORR-TMS-8800",
        source_connection_id=conn.id,
        source_replica_id=replica.id,
        load_reference_number=str(normalized_dto.data["load_reference_number"]),
        carrier_scac=str(normalized_dto.data["carrier_scac"]),
        origin_city=str(normalized_dto.data["origin_city"]),
        origin_state=str(normalized_dto.data["origin_state"]),
        destination_city=str(normalized_dto.data["destination_city"]),
        destination_state=str(normalized_dto.data["destination_state"]),
        status=str(normalized_dto.data["status"]),
        total_weight_lbs=41200.0,
        freight_charge_usd=Decimal("2950.00"),
        pickup_scheduled_at=now,
        delivery_scheduled_at=now,
        updated_at=now,
    )
    tms_repo = SqlAlchemyTmsDomainRepository(tenant_session)
    await tms_repo.save_load(load_dto)

    gem_repo = SqlAlchemyGlobalEntityMapRepository(tenant_session)
    gem = GlobalEntityMap.create(
        tenant_id=seeded_ip_tenant,
        trace_id=trace_id,
        correlation_id="CORR-TMS-8800",
        entity_domain=TmsEntityType.TMS_LOAD,
        canonical_id=load_dto.id,
        source_connection_id=conn.id,
        source_entity_id=replica.record_key,
    )
    gem.bind_destination("ip_conn_netsuite", "NS-INV-8800")
    await gem_repo.save(gem)

    outbound_repo = SqlAlchemyOutboundRecordRepository(tenant_session)
    outbound = OutboundRecord.create_pending(
        tenant_id=seeded_ip_tenant,
        connection_id="ip_conn_netsuite",
        app_id="netsuite",
        stream_name="freight_invoices",
        target_url="https://netsuite.enterprise.com/api/invoices",
        http_method="POST",
        payload_bytes=b'{"inv":"NS-INV-8800"}',
        is_inlined=True,
        trace_id=trace_id,
        correlation_id="CORR-TMS-8800",
        request_headers={"Content-Type": "application/json"},
        request_body={"inv": "NS-INV-8800"},
    )
    outbound.mark_delivered(
        response_status_code=200,
        response_headers={"Content-Type": "application/json"},
        response_body={"ns_id": "NS-INV-8800"},
        duration_ms=35,
    )
    await outbound_repo.save(outbound)

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
