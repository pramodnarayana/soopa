"""Narrow integration tests for EDI Trace, Lineage, and Stage Replay against real PostgreSQL with SAVEPOINT rollback."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from edi.application.use_cases.replay.bulk_replay_stage_use_case import (
    BulkReplayStageCommand,
    BulkReplayStageUseCase,
)
from edi.application.use_cases.replay.modify_and_replay_use_case import (
    ModifyAndReplayCommand,
    ModifyAndReplayUseCase,
)
from edi.application.use_cases.replay.replay_stage_use_case import (
    ReplayStageCommand,
    ReplayStageUseCase,
)
from edi.application.use_cases.replay.stage_replay_processor import (
    build_default_edi_stage_replay_processors,
)
from edi.application.use_cases.trace.get_edi_trace_lineage_use_case import (
    GetEdiTraceLineageQuery,
    GetEdiTraceLineageUseCase,
)
from edi.application.use_cases.trace.get_edi_trace_use_case import (
    GetEdiTraceQuery,
    GetEdiTraceUseCase,
)
from edi.bootstrap.container import create_edi_data_plane_uow
from edi.domain.enums import EdiTraceEventType
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus, ReplayCheckpoint
from edi.domain.transaction.gateway_receipt import ApiGatewayReceipt
from edi.testing.fakes.pipeline_fakes import InMemoryStorageAdapter

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def tenant_session(
    tenant_db_connection: AsyncConnection,
) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = async_sessionmaker(
        bind=tenant_db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        info={"session_type": "tenant"},
    )
    async with SessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_replay_transform_queues_stage_record(tenant_session: AsyncSession) -> None:
    uow = create_edi_data_plane_uow(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-1"
    trace_id = f"trace-{uuid.uuid4()}"

    await uow.edi_messages.save(
        EdiMessage(
            id=f"edi_msg_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            trace_id=trace_id,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            edi_data="raw data",
        )
    )

    service = ReplayStageUseCase(uow, build_default_edi_stage_replay_processors())
    replay_res = await service.execute(
        ReplayStageCommand(
            tenant_id=tenant_id,
            trace_id=trace_id,
            checkpoint=ReplayCheckpoint.TRANSFORM,
            actor="api-user",
        )
    )
    assert replay_res.is_ok
    new_trace_id = replay_res.unwrap()

    result = await tenant_session.execute(
        text(
            "SELECT payload FROM outbox WHERE event_type = 'TRANSFORMATION_REQUESTED' AND tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)

    assert payload["trace_id"] == new_trace_id


@pytest.mark.asyncio
async def test_replay_deliver_queues_stage_record(tenant_session: AsyncSession) -> None:
    uow = create_edi_data_plane_uow(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-1"
    trace_id = f"trace-{uuid.uuid4()}"

    await uow.edi_messages.save(
        EdiMessage(
            id=f"edi_msg_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            trace_id=trace_id,
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.PENDING_DELIVERY,
            edi_data="raw data",
        )
    )

    service = ReplayStageUseCase(uow, build_default_edi_stage_replay_processors())
    replay_res = await service.execute(
        ReplayStageCommand(
            tenant_id=tenant_id,
            trace_id=trace_id,
            checkpoint=ReplayCheckpoint.DELIVERY,
            actor="api-user",
        )
    )
    assert replay_res.is_ok
    new_trace_id = replay_res.unwrap()

    result = await tenant_session.execute(
        text(
            "SELECT payload FROM outbox WHERE event_type = 'DELIVERY_REQUESTED' AND tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)

    assert payload["trace_id"] == new_trace_id


@pytest.mark.asyncio
async def test_bulk_replay_queues_each_unique_stage_record(
    tenant_session: AsyncSession,
) -> None:
    uow = create_edi_data_plane_uow(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-bulk"
    trace_id_1 = f"trace-{uuid.uuid4()}"
    trace_id_2 = f"trace-{uuid.uuid4()}"

    await uow.edi_messages.save(
        EdiMessage(
            id=f"edi_msg_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            trace_id=trace_id_1,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            edi_data="raw data",
        )
    )
    await uow.edi_messages.save(
        EdiMessage(
            id=f"edi_msg_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            trace_id=trace_id_2,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            edi_data="raw data",
        )
    )

    service = BulkReplayStageUseCase(uow, build_default_edi_stage_replay_processors())
    command_key = f"cmd-{uuid.uuid4()}"

    bulk_res = await service.execute(
        BulkReplayStageCommand(
            tenant_id=tenant_id,
            trace_ids=(trace_id_1, trace_id_2),
            checkpoint=ReplayCheckpoint.TRANSFORM,
            actor="api-user",
            command_key=command_key,
        )
    )
    assert bulk_res.is_ok
    count = bulk_res.unwrap()

    assert count == 2

    VerificationSession = async_sessionmaker(
        bind=tenant_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        info={"session_type": "tenant"},
    )
    async with VerificationSession() as verification_session:
        result = await verification_session.execute(
            text(
                "SELECT idempotency_key FROM outbox WHERE event_type = 'TRANSFORMATION_REQUESTED' AND tenant_id = :tenant_id ORDER BY idempotency_key"
            ),
            {"tenant_id": tenant_id},
        )
        rows = result.fetchall()
    assert len(rows) == 2

    keys = {row[0] for row in rows}
    assert keys == {
        f"{command_key}_0",
        f"{command_key}_1",
    }

    events_1 = await uow.traces.list_trace_events(tenant_id, trace_id_1)
    assert len(events_1) == 1
    assert events_1[0].event_type == EdiTraceEventType.REPLAY_TRANSFORM.value


@pytest.mark.asyncio
async def test_edi_trace_waterfall_s3_hydration_and_parent_fallback_against_postgres(
    tenant_session: AsyncSession,
) -> None:
    storage = InMemoryStorageAdapter()
    msg_uri = await storage.upload(b"ISA*00*HYDRATED_EDI~", "edi/raw", "msg1.edi")

    uow = create_edi_data_plane_uow(tenant_session, storage)
    tenant_id = "tenant-trace-hydration"
    root_trace_id = f"trace-root-{uuid.uuid4()}"

    await uow.edi_messages.save(
        EdiMessage(
            id=f"edi_msg_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            trace_id=root_trace_id,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.TRANSFORMED,
            storage_uri=msg_uri,
            interchange_control_no="ICN-8801",
            message_id="MSG-8801",
            original_trace_id=root_trace_id,
        )
    )
    await uow.edi_jsons.save(
        EdiJson(
            id=f"edi_json_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            trace_id=root_trace_id,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            transaction_type="850",
            payload={"BEG": {"BEG03": "PO-8801"}},
            original_trace_id=root_trace_id,
        )
    )
    await uow.api_gateway_receipts.save(
        ApiGatewayReceipt(
            id=f"edi_gw_{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            trace_id=root_trace_id,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            http_status_code=502,
            payload={"error": "Bad Gateway"},
        )
    )

    replay_svc = ReplayStageUseCase(uow, build_default_edi_stage_replay_processors())
    child_res = await replay_svc.execute(
        ReplayStageCommand(
            tenant_id=tenant_id,
            trace_id=root_trace_id,
            checkpoint=ReplayCheckpoint.DELIVERY,
            actor="ops@soopa.io",
        )
    )
    assert child_res.is_ok
    child_trace_id = child_res.unwrap()

    trace_svc = GetEdiTraceUseCase(uow)
    trace_res = await trace_svc.execute(
        GetEdiTraceQuery(tenant_id=tenant_id, trace_id=child_trace_id)
    )
    assert trace_res.is_ok
    child_trace = trace_res.unwrap()
    assert child_trace.edi_message is not None
    assert child_trace.edi_message.trace_id == root_trace_id
    assert child_trace.edi_message.edi_data == "ISA*00*HYDRATED_EDI~"
    assert len(child_trace.edi_jsons) == 1
    assert child_trace.edi_jsons[0].trace_id == child_trace_id
    assert child_trace.edi_jsons[0].parent_trace_id == root_trace_id
    assert child_trace.edi_jsons[0].original_trace_id == root_trace_id
    assert child_trace.edi_jsons[0].replay_count == 1

    repo_lineage = await uow.traces.get_trace_lineage(tenant_id, child_trace_id)
    assert len(repo_lineage) == 2
    assert repo_lineage[0].trace_id == root_trace_id
    assert repo_lineage[0].primary_layer == "STAGE_3_DELIVER"
    assert repo_lineage[1].trace_id == child_trace_id
    assert repo_lineage[1].primary_layer == "STAGE_2_TRANSFORM"
    assert repo_lineage[1].replay_count == 1

    corr_matches = await uow.traces.find_traces_by_correlation_id(tenant_id, "ICN-8801")
    assert len(corr_matches) == 1
    assert corr_matches[0].trace_id == root_trace_id


@pytest.mark.asyncio
async def test_modify_and_replay_and_get_lineage_use_case_against_postgres(
    tenant_session: AsyncSession,
) -> None:
    uow = create_edi_data_plane_uow(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-modify-replay"
    root_trace_id = f"trace-mod-{uuid.uuid4()}"

    msg = EdiMessage.create_inbound(
        id=f"edi_msg_{uuid.uuid4().hex[:12]}",
        trace_id=root_trace_id,
        tenant_id=tenant_id,
        edi_data="ISA*00*BAD~",
        status=MessageStatus.RECEIVED.value,
        trading_partner_id="tp_1",
        sender_id="SND",
        receiver_id="RCV",
        connection_type="AS2",
    )
    msg.mark_transform_failed("Segment error")
    await uow.edi_messages.save(msg)

    mod_svc = ModifyAndReplayUseCase(uow)
    mod_res = await mod_svc.execute(
        ModifyAndReplayCommand(
            tenant_id=tenant_id,
            original_trace_id=root_trace_id,
            modified_payload="ISA*00*FIXED~",
            actor="ops@soopa.io",
        )
    )
    assert mod_res.is_ok
    new_trace_id = mod_res.unwrap()

    root_events = await uow.traces.list_trace_events(tenant_id, root_trace_id)
    assert [e.event_type for e in root_events] == [
        EdiTraceEventType.TRANSFORMATION_FAILED.value,
        EdiTraceEventType.MODIFY_AND_REPLAY_TRANSFORM.value,
    ]
    new_events = await uow.traces.list_trace_events(tenant_id, new_trace_id)
    assert [e.event_type for e in new_events] == [
        EdiTraceEventType.CREATED_FROM_MODIFICATION.value,
    ]

    lineage_svc = GetEdiTraceLineageUseCase(uow)
    lineage = await lineage_svc.execute(
        GetEdiTraceLineageQuery(tenant_id=tenant_id, trace_id=new_trace_id)
    )
    assert [item.trace_id for item in lineage] == [root_trace_id, new_trace_id]
