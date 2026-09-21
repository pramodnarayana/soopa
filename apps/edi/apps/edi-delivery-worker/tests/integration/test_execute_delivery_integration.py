import contextlib

import pytest
from database.testing import TransactionalTestRouter
from edi.adapters.outbound.database.data_plane.uow import SqlAlchemyDataPlaneUnitOfWork
from edi.adapters.outbound.pipeline.http import HttpxDeliveryClient
from edi.config.settings import get_settings
from pytest_httpserver import HTTPServer
from seedwork import generate_random_hex
from sqlalchemy import text

from edi_delivery_worker.data.main import _setup_registry


class FakeSftpDeliveryClient:
    pass


class FakeAs2DeliveryClient:
    pass


class FakeVault:
    async def get_secret(self, key):
        return "secret"


class FakeStorage:
    pass


class FakeTenantUowProvider:
    def __init__(self, db_router):
        self.db_router = db_router

    async def get_uow_factory(self, tenant_id: str):
        @contextlib.asynccontextmanager
        async def factory():
            async for session in self.db_router.get_tenant_session(
                tenant_id, "fake_shard", "fake_dsn"
            ):
                yield SqlAlchemyDataPlaneUnitOfWork(session, FakeStorage())

        return factory


@pytest.mark.asyncio
@pytest.mark.integration
async def test_execute_delivery_integration(
    db_router: TransactionalTestRouter, httpserver: HTTPServer
) -> None:
    tenant_id = f"ten_deliv_{generate_random_hex(6)}"
    trace_id = f"trace_{generate_random_hex(6)}"
    partner_id = f"partner_{generate_random_hex(6)}"

    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, idp_tenant_id, created_at, updated_at) VALUES (:id, 'Test', :slug, 'active', 'idp_123', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"deliv-{generate_random_hex(6)}"},
    )

    async for test_session in db_router.get_shard_session("fake_shard", "fake_dsn"):
        await test_session.execute(
            text("""
                INSERT INTO edi_messages
                (id, trace_id, tenant_id, sender_id, receiver_id, direction, format_standard, transaction_type, status, edi_data, replay_count)
                VALUES (:id, :id, :tenant_id, 'sender1', 'receiver1', 'OUTBOUND', 'X12', '850', 'TRANSFORMED', 'test_data', 0)
            """),
            {"id": trace_id, "tenant_id": tenant_id},
        )
        await test_session.commit()

        webhook_target_url = httpserver.url_for("/webhook")

        # Insert a webhook route
        await test_session.execute(
            text("""
                INSERT INTO webhooks
                (id, tenant_id, name, url, auth_header_vault_ref, active, created_at, updated_at)
                VALUES (:partner_id, :tenant_id, 'Test', :url, 'fake_ref', true, NOW(), NOW())
            """),
            {"partner_id": partner_id, "tenant_id": tenant_id, "url": webhook_target_url},
        )
        await test_session.commit()

        # Insert API payload
        await test_session.execute(
            text("""
                INSERT INTO api_gateway
                (id, trace_id, tenant_id, direction, payload, status, created_at, updated_at)
                VALUES (:id, :trace_id, :tenant_id, 'INBOUND', '{"test": "payload"}', 'RECEIVED', NOW(), NOW())
            """),
            {"id": f"api_{generate_random_hex(6)}", "trace_id": trace_id, "tenant_id": tenant_id},
        )
        await test_session.commit()

    httpserver.expect_request("/webhook", method="POST").respond_with_json({"status": "ok"})

    http_delivery = HttpxDeliveryClient(validator=lambda url: True, allow_private_ips=True)
    uow_provider = FakeTenantUowProvider(db_router)
    settings = get_settings()

    dispatcher = _setup_registry(
        settings=settings,
        uow_provider=uow_provider,
        http_delivery=http_delivery,
        sftp_delivery=FakeSftpDeliveryClient(),
        as2_delivery=FakeAs2DeliveryClient(),
        vault=FakeVault(),
    )

    event = {
        "tenant_id": tenant_id,
        "event_type": "EXECUTE_DELIVERY_COMMAND",
        "idempotency_key": "idemp_1",
        "payload": {
            "trace_id": trace_id,
            "tenant_id": tenant_id,
            "partner_id": partner_id,
            "strategy_type": "webhook_id",
        },
    }

    await dispatcher.handle(event)

    httpserver.check_assertions()
    assert len(httpserver.log) == 1
    req, _ = httpserver.log[0]
    assert req.method == "POST"

    # Verify domain event in outbox
    async for test_session in db_router.get_tenant_session(tenant_id, "fake_shard", "fake_dsn"):
        res = await test_session.execute(
            text(
                "SELECT payload FROM outbox WHERE event_type = 'DELIVERY_SUCCESSFUL' AND payload->>'trace_id' = :trace_id"
            ),
            {"trace_id": trace_id},
        )
        outbox_row = res.fetchone()
        assert outbox_row is not None
        assert outbox_row[0]["trace_id"] == trace_id
