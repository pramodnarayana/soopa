import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from edi.adapters.outbound.database.uow_adapter import SqlAlchemyDataPlaneUnitOfWork
from edi.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
)
from edi.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionUseCase,
)
from edi.testing.fakes.pipeline_fakes import InMemoryStorageAdapter


@pytest_asyncio.fixture
async def tenant_session(tenant_db_connection):
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
async def test_replay_queues_validated_transaction(tenant_session):
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-1"
    trace_id = f"trace-{uuid.uuid4()}"

    # Pre-seed the DB with an EdiMessage
    await uow.transactions.create_edi_message(
        tenant_id,
        {
            "trace_id": trace_id,
            "direction": "INBOUND",
            "status": "RECEIVED",
            "edi_data": "raw data",
        },
    )

    service = ReplayTransactionUseCase(uow)
    await service.replay_transaction(tenant_id, trace_id, "raw")

    # Assert event in outbox
    result = await tenant_session.execute(
        text(
            "SELECT payload FROM outbox WHERE event_type = 'edi.transaction.replay_requested' AND tenant_id = :tenant_id"
        ),
        {"tenant_id": tenant_id},
    )
    row = result.fetchone()
    assert row is not None
    payload = row[0]
    if isinstance(payload, str):
        payload = json.loads(payload)

    assert payload["trace_id"] == trace_id
    assert payload["tier"] == "raw"


@pytest.mark.asyncio
async def test_bulk_replay_queues_each_unique_validated_transaction(tenant_session):
    uow = SqlAlchemyDataPlaneUnitOfWork(tenant_session, InMemoryStorageAdapter())
    tenant_id = "tenant-bulk"
    trace_id_1 = f"trace-{uuid.uuid4()}"
    trace_id_2 = f"trace-{uuid.uuid4()}"

    # Pre-seed the DB
    await uow.transactions.create_edi_message(
        tenant_id,
        {
            "trace_id": trace_id_1,
            "direction": "INBOUND",
            "status": "RECEIVED",
            "edi_data": "raw data",
        },
    )
    await uow.transactions.create_edi_message(
        tenant_id,
        {
            "trace_id": trace_id_2,
            "direction": "INBOUND",
            "status": "RECEIVED",
            "edi_data": "raw data",
        },
    )

    service = BulkReplayTransactionsUseCase(uow)
    command_key = f"cmd-{uuid.uuid4()}"

    count = await service.bulk_replay_transactions(
        tenant_id, [trace_id_1, trace_id_2, trace_id_1], "raw", command_key=command_key
    )

    assert count == 3

    # Verify exactly 3 events with the idempotency key sequence
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
                "SELECT idempotency_key FROM outbox WHERE event_type = 'edi.transaction.replay_requested' AND tenant_id = :tenant_id ORDER BY idempotency_key"
            ),
            {"tenant_id": tenant_id},
        )
        rows = result.fetchall()
    assert len(rows) == 3

    keys = {row[0] for row in rows}
    assert keys == {
        f"bulk_replay_{command_key}_0",
        f"bulk_replay_{command_key}_1",
        f"bulk_replay_{command_key}_2",
    }
