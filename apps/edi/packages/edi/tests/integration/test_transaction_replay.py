"""Narrow integration tests for EDI Trace, Lineage, and Replay against real PostgreSQL with SAVEPOINT rollback."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from strace.domain import TraceEventType

from edi.adapters.outbound.database.data_plane.uow import SqlAlchemyDataPlaneUnitOfWork
from edi.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
)
from edi.application.use_cases.transactions.get_edi_trace_lineage_use_case import (
    GetEdiTraceLineageUseCase,
)
from edi.application.use_cases.transactions.get_edi_trace_use_case import (
    GetEdiTraceUseCase,
)
from edi.application.use_cases.transactions.modify_and_replay_use_case import (
    ModifyAndReplayTransactionUseCase,
)
from edi.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionUseCase,
)
from edi.domain.enums import EdiDirection, MessageStatus
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.ports.outbound.api_gateway_repository import CreateApiGatewayCommand
from edi.ports.outbound.transaction_repository import (
    CreateEdiJsonCommand,
    CreateEdiMessageCommand,
)
from edi.testing.fakes.pipeline_fakes import FakeOutboxPublisher, InMemoryStorageAdapter

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
async def test_replay_queues_validated_transaction(tenant_session: AsyncSession) -> None:
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-1"
    trace_id = f"trace-{uuid.uuid4()}"

    await uow.transactions.create_edi_message(
        command=CreateEdiMessageCommand(
            tenant_id=tenant_id,
            trace_id=trace_id,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            edi_data="raw data",
        )
    )

    service = ReplayTransactionUseCase(uow, publisher=FakeOutboxPublisher())
    new_trace_id = await service.retry_transform(tenant_id, trace_id, "api-user")

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
async def test_replay_deliver_queues_validated_transaction(tenant_session: AsyncSession) -> None:
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-1"
    trace_id = f"trace-{uuid.uuid4()}"

    await uow.transactions.create_edi_message(
        command=CreateEdiMessageCommand(
            tenant_id=tenant_id,
            trace_id=trace_id,
            direction=EdiDirection.OUTBOUND,
            status=MessageStatus.PENDING_DELIVERY,
            edi_data="raw data",
        )
    )

    service = ReplayTransactionUseCase(uow, publisher=FakeOutboxPublisher())
    new_trace_id = await service.retry_deliver(tenant_id, trace_id, "api-user")

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
async def test_bulk_replay_queues_each_unique_validated_transaction(
    tenant_session: AsyncSession,
) -> None:
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-bulk"
    trace_id_1 = f"trace-{uuid.uuid4()}"
    trace_id_2 = f"trace-{uuid.uuid4()}"

    await uow.transactions.create_edi_message(
        command=CreateEdiMessageCommand(
            tenant_id=tenant_id,
            trace_id=trace_id_1,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            edi_data="raw data",
        )
    )
    await uow.transactions.create_edi_message(
        command=CreateEdiMessageCommand(
            tenant_id=tenant_id,
            trace_id=trace_id_2,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            edi_data="raw data",
        )
    )

    service = BulkReplayTransactionsUseCase(uow, publisher=FakeOutboxPublisher())
    command_key = f"cmd-{uuid.uuid4()}"

    count = await service.bulk_retry_transform(
        tenant_id, [trace_id_1, trace_id_2], "api-user", command_key=command_key
    )

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

    # Verify audit trace events were persisted via uow.traces.save_all_trace_events
    events_1 = await uow.traces.list_trace_events(tenant_id, trace_id_1)
    assert len(events_1) == 1
    assert events_1[0].event_type == TraceEventType.REPLAY_TRANSFORM.value


@pytest.mark.asyncio
async def test_edi_trace_waterfall_s3_hydration_and_parent_fallback_against_postgres(
    tenant_session: AsyncSession,
) -> None:
    storage = InMemoryStorageAdapter()
    msg_uri = await storage.upload(b"ISA*00*HYDRATED_EDI~", "edi/raw", "msg1.edi")

    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, storage)
    tenant_id = "tenant-trace-hydration"
    root_trace_id = f"trace-root-{uuid.uuid4()}"

    # 1. Create Stage 1 EdiMessage (with S3 storage_uri), Stage 2 EdiJson, and Stage 3 ApiGateway
    await uow.transactions.create_edi_message(
        command=CreateEdiMessageCommand(
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
    await uow.transactions.create_edi_json(
        command=CreateEdiJsonCommand(
            tenant_id=tenant_id,
            trace_id=root_trace_id,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            transaction_type="850",
            payload={"BEG": {"BEG03": "PO-8801"}},
            original_trace_id=root_trace_id,
        )
    )
    await uow.api_gateway_transactions.create_api_gateway(
        command=CreateApiGatewayCommand(
            tenant_id=tenant_id,
            trace_id=root_trace_id,
            direction=EdiDirection.INBOUND,
            status=MessageStatus.FAILED,
            http_status_code=502,
            payload={"error": "Bad Gateway"},
        )
    )

    # 2. Trigger a DELIVERY replay (which only clones EdiJson onto child_trace_id)
    replay_svc = ReplayTransactionUseCase(uow, publisher=FakeOutboxPublisher())
    child_trace_id = await replay_svc.retry_deliver(tenant_id, root_trace_id, "ops@soopa.io")

    # 3. Verify GetEdiTraceUseCase on child_trace_id hydrates EdiMessage from parent_trace_id + S3!
    trace_svc = GetEdiTraceUseCase(uow)
    child_trace = await trace_svc.get_edi_trace(tenant_id, child_trace_id)
    assert child_trace.edi_message is not None
    assert child_trace.edi_message.trace_id == root_trace_id
    assert child_trace.edi_message.edi_data == "ISA*00*HYDRATED_EDI~"
    assert len(child_trace.edi_jsons) == 1
    assert child_trace.edi_jsons[0].trace_id == child_trace_id
    assert child_trace.edi_jsons[0].parent_trace_id == root_trace_id
    assert child_trace.edi_jsons[0].original_trace_id == root_trace_id
    assert child_trace.edi_jsons[0].replay_count == 1

    # 4. Verify uow.traces (SqlAlchemyTraceRepository) lineage and correlation lookup
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
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-modify-replay"
    root_trace_id = f"trace-mod-{uuid.uuid4()}"

    msg = EdiMessageDomainModel.create_inbound(
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
    await uow.transactions.save(msg)

    mod_svc = ModifyAndReplayTransactionUseCase(uow, publisher=FakeOutboxPublisher())
    new_trace_id = await mod_svc.execute(
        tenant_id=tenant_id,
        original_trace_id=root_trace_id,
        modified_payload="ISA*00*FIXED~",
        actor="ops@soopa.io",
    )

    root_events = await uow.traces.list_trace_events(tenant_id, root_trace_id)
    assert [e.event_type for e in root_events] == [
        TraceEventType.TRANSFORMATION_FAILED.value,
        TraceEventType.MODIFY_AND_REPLAY_TRANSFORM.value,
    ]
    new_events = await uow.traces.list_trace_events(tenant_id, new_trace_id)
    assert [e.event_type for e in new_events] == [
        TraceEventType.CREATED_FROM_MODIFICATION.value,
    ]

    lineage_svc = GetEdiTraceLineageUseCase(uow)
    lineage = await lineage_svc.execute(tenant_id, new_trace_id)
    assert [item.trace_id for item in lineage] == [root_trace_id, new_trace_id]
