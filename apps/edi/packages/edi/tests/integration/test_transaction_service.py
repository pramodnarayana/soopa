import uuid
from unittest.mock import MagicMock

import pytest
from database.models.data_plane import EdiMessage

from edi.adapters.uow_adapter import SqlAlchemyDataPlaneUnitOfWork
from edi.core.exceptions import TransactionNotFoundError
from edi.core.services.transaction_service import TransactionService


@pytest.fixture
def uow(db_session):
    db_session.info["session_type"] = "tenant"
    return SqlAlchemyDataPlaneUnitOfWork(tenant_session=db_session)


@pytest.fixture
def mock_routing_resolver():
    resolver = MagicMock()
    # Mock resolve_routing_context to return (trading_partner_name, connection_type)
    # Because it is an async method in reality, we need an AsyncMock.

    async def mock_resolve(*args, **kwargs):
        return ("Acme Corp", "AS2")

    resolver.resolve_routing_context = mock_resolve
    return resolver


@pytest.mark.asyncio
async def test_replay_transaction_not_found(uow):
    svc = TransactionService(uow=uow)

    with pytest.raises(TransactionNotFoundError):
        await svc.replay_transaction(tenant_id="tenant-1", trace_id=str(uuid.uuid4()), tier="raw")


@pytest.mark.asyncio
async def test_replay_transaction_success(uow, db_session):
    # Setup Data
    tenant_id = "tenant-1"
    trace_id = str(uuid.uuid4())

    msg = EdiMessage(
        tenant_id=tenant_id,
        trace_id=trace_id,
        direction="INBOUND",
        transaction_type="850",
        sender_id="SENDER123",
        receiver_id="RECEIVER123",
        status="PROCESSED",
        edi_data="test_data",
    )
    db_session.add(msg)
    await db_session.commit()

    svc = TransactionService(uow=uow)

    # Execute Replay
    await svc.replay_transaction(tenant_id=tenant_id, trace_id=trace_id, tier="raw")

    # Assert Outbox Event was created
    async with uow:
        from database.models.data_plane import DataPlaneOutbox
        from sqlalchemy import func, select

        res = await db_session.execute(
            select(func.count())
            .select_from(DataPlaneOutbox)
            .where(DataPlaneOutbox.event_type == "edi.transaction.replay_requested")
        )
        count = res.scalar()
        assert count == 1


@pytest.mark.asyncio
async def test_bulk_replay_transaction_success(uow, db_session):
    # Setup Data
    tenant_id = "tenant-1"
    trace_id_1 = str(uuid.uuid4())
    trace_id_2 = str(uuid.uuid4())

    msg1 = EdiMessage(
        tenant_id=tenant_id,
        trace_id=trace_id_1,
        direction="INBOUND",
        transaction_type="850",
        sender_id="S1",
        receiver_id="R1",
        status="PROCESSED",
        edi_data="test_data",
    )
    msg2 = EdiMessage(
        tenant_id=tenant_id,
        trace_id=trace_id_2,
        direction="INBOUND",
        transaction_type="850",
        sender_id="S1",
        receiver_id="R1",
        status="PROCESSED",
        edi_data="test_data",
    )
    db_session.add_all([msg1, msg2])
    await db_session.commit()

    svc = TransactionService(uow=uow)

    # Execute Bulk Replay
    await svc.bulk_replay_transactions(
        tenant_id=tenant_id, trace_ids=[trace_id_1, trace_id_2], tier="translation"
    )

    # Assert Outbox Events were created
    async with uow:
        from database.models.data_plane import DataPlaneOutbox
        from sqlalchemy import func, select

        res = await db_session.execute(
            select(func.count())
            .select_from(DataPlaneOutbox)
            .where(DataPlaneOutbox.payload["tier"].astext == "translation")
        )
        count = res.scalar()
        assert count == 2


@pytest.mark.asyncio
async def test_get_transaction_success(uow, db_session, mock_routing_resolver):
    # Setup Data
    tenant_id = "tenant-1"
    trace_id = str(uuid.uuid4())

    msg = EdiMessage(
        tenant_id=tenant_id,
        trace_id=trace_id,
        direction="INBOUND",
        transaction_type="850",
        connection_type="UNKNOWN",
        sender_id="SENDER123",
        receiver_id="RECEIVER123",
        status="PROCESSED",
        edi_data="test_data",
    )
    db_session.add(msg)
    await db_session.commit()

    svc = TransactionService(uow=uow)

    # Execute Get Transaction
    result = await svc.get_transaction(
        tenant_id=tenant_id, trace_id=trace_id, routing_resolver=mock_routing_resolver
    )

    assert result.edi_message["trace_id"] == trace_id
    assert result.edi_message["connection_type"] == "AS2"  # Mutated by routing resolver
    assert result.trading_partner_name == "Acme Corp"
