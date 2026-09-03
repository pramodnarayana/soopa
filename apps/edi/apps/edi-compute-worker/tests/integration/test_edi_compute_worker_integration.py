import asyncio
import contextlib
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from edi.adapters.outbound.database.uow_adapter import SqlAlchemyDataPlaneUnitOfWork
from edi.application.use_cases.pipeline.compute_transform_use_case import ComputeTransformUseCase
from edi.ports.outbound.transformer_port import TransformedTransaction, TransformerPort
from edi.testing.fakes.pipeline_fakes import InMemoryStorageAdapter
from seedwork import generate_random_hex
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from compute_worker.compute_dispatcher import EdiComputeDispatcher


class MockTransformerAdapter(TransformerPort):
    async def transform_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> list[TransformedTransaction]:
        return [
            TransformedTransaction(
                transaction_type="850",
                isa_sender_id="SENDER123",
                isa_receiver_id="RECEIVER123",
                gs_sender_id="SENDER123",
                gs_receiver_id="RECEIVER123",
                control_number="0001",
                payload={"purchase_order": "PO-12345"},
            )
        ]

    async def transform_json_to_edi(
        self,
        payload: dict[str, Any] | list[Any],
        standard: str,
        transaction_type: str,
        route_config: dict[str, Any],
    ) -> bytes:
        return b"ISA*00*          *00*          *ZZ*SENDER123      *ZZ*RECEIVER123    *230101*1200*U*00401*000000001*0*T*:~"


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncGenerator[Any, None]:
    db_url = "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1"
    engine = create_async_engine(db_url, echo=True, future=True, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_connection(db_engine) -> AsyncGenerator[AsyncConnection, None]:
    connection = await db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
def db_session_factory(db_connection) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        info={"session_type": "tenant"},
    )


@pytest.mark.asyncio
async def test_compute_worker_transforms_edi_and_publishes_event(
    db_engine,
    db_connection: AsyncConnection,
    db_session_factory: async_sessionmaker,
) -> None:
    # 1. Wire the Use Case Factory
    transformer = MockTransformerAdapter()

    async def fake_use_case_factory(tenant_id: str):
        @contextlib.asynccontextmanager
        async def fake_uow_factory():
            yield SqlAlchemyDataPlaneUnitOfWork(
                tenant_session=db_session_factory(), storage=InMemoryStorageAdapter()
            )

        return ComputeTransformUseCase(uow_factory=fake_uow_factory, transformer=transformer)

    dispatcher = EdiComputeDispatcher(use_case_factory=fake_use_case_factory)

    # 2. Seed test data completely outside the pytest connection boundary
    #    to avoid asyncpg constraint race conditions. We use an autonomous engine connection.
    trace_id = f"trace_{generate_random_hex(6)}"
    tenant_id = f"tenant_{generate_random_hex(6)}"
    partner_id = f"tp_{generate_random_hex(6)}"
    webhook_id = f"wh_{generate_random_hex(6)}"
    route_id = f"route_{generate_random_hex(6)}"
    msg_id = f"msg_{generate_random_hex(6)}"

    # We manually assign the ID to bypass the default UUID/hex generator for predictable assertions
    # Seed data autonomously to prevent test isolation bugs
    async with db_engine.connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO edi.as2_partners (id, tenant_id, name, as2_id, active, is_local, created_at, updated_at) VALUES (:pid, :tid, 'Test Partner', 'AS2TEST', true, false, NOW(), NOW())"
            ),
            {"pid": partner_id, "tid": tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO edi.webhooks (id, tenant_id, name, url, active, created_at, updated_at) VALUES (:wid, :tid, 'Test Webhook', 'https://test.com/webhook', true, NOW(), NOW())"
            ),
            {"wid": webhook_id, "tid": tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO edi.inbound_routes (id, tenant_id, name, trading_partner_id, webhook_id, isa_sender_id, isa_receiver_id, transaction_type, active, processing_mode, created_at, updated_at) VALUES (:rid, :tid, 'Route', :pid, :wid, 'SENDER123', 'RECEIVER123', '850', true, 'TRANSFORM', NOW(), NOW())"
            ),
            {"rid": route_id, "tid": tenant_id, "pid": partner_id, "wid": webhook_id},
        )
        await conn.execute(
            text(
                "INSERT INTO edi.edi_messages (id, trace_id, tenant_id, direction, transaction_type, status, sender_id, receiver_id, edi_data, is_resend, created_at, updated_at) VALUES (:mid, :trid, :tid, 'INBOUND', '850', 'RECEIVED', 'SENDER123', 'RECEIVER123', 'ISA*00...', false, NOW(), NOW())"
            ),
            {"mid": msg_id, "trid": trace_id, "tid": tenant_id},
        )
        await conn.commit()

    # 3. Run the compute worker.
    try:
        await dispatcher.dispatch_raw(
            body_json={"trace_id": trace_id, "tenant_id": tenant_id, "step": "COMPUTE_TRANSFORM"}
        )

        # 4. Verify outcomes.
        res = await db_connection.execute(
            text("SELECT status, payload FROM edi.edi_json WHERE trace_id = :tid"),
            {"tid": trace_id},
        )
        json_rows = res.fetchall()
        assert len(json_rows) == 1
        assert json_rows[0].status == "PARSED"

        # Verify API Gateway request was created.
        res = await db_connection.execute(
            text("SELECT status, webhook_url, payload FROM edi.api_gateway WHERE trace_id = :tid"),
            {"tid": trace_id},
        )
        gw_rows = res.fetchall()
        assert len(gw_rows) == 1
        assert gw_rows[0].webhook_url == "https://test.com/webhook"

        # Verify Outbox event was published.
        res = await db_connection.execute(
            text("SELECT status, event_type FROM edi.outbox WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        outbox_rows = res.fetchall()
        assert len(outbox_rows) == 1
        assert outbox_rows[0].event_type == "TRANSFORM_COMPLETED"
    finally:
        # Cleanup seeded data autonomously
        async with db_engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM edi.edi_messages WHERE id = :mid"), {"mid": msg_id}
            )
            await conn.execute(
                text("DELETE FROM edi.inbound_routes WHERE id = :rid"), {"rid": route_id}
            )
            await conn.execute(
                text("DELETE FROM edi.webhooks WHERE id = :wid"), {"wid": webhook_id}
            )
            await conn.execute(
                text("DELETE FROM edi.as2_partners WHERE id = :pid"), {"pid": partner_id}
            )
            await conn.commit()
