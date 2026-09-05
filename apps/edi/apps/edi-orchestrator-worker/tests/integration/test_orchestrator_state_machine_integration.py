import contextlib
from collections.abc import Callable
from typing import Any

import pytest
from database.testing import TransactionalTestRouter
from edi.adapters.outbound.database.data_plane_unit_of_work import SqlAlchemyDataPlaneUnitOfWork
from edi.adapters.outbound.pipeline.http import HttpxDeliveryClient
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase
from edi.application.use_cases.pipeline.dispatch_inbound_transform_use_case import (
    DispatchInboundTransformUseCase,
)
from edi.config.settings import get_settings
from edi.core.pipeline.delivery.webhook import WebhookDeliveryStrategy
from edi.domain.enums import PipelineEventType
from pytest_httpserver import HTTPServer
from seedwork import generate_random_hex
from sqlalchemy import text

from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry


@pytest.mark.asyncio
@pytest.mark.integration
async def test_inbound_routing_state_machine_transition(db_router: TransactionalTestRouter) -> None:
    # 1. Setup DB Data
    tenant_id = f"ten_orch_{generate_random_hex(6)}"
    trace_id = f"trace_{generate_random_hex(6)}"

    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, idp_tenant_id, created_at, updated_at) VALUES (:id, 'Test', :slug, 'active', 'idp_123', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"orch-{generate_random_hex(6)}"},
    )

    # We must insert an edi_message so the use case can read it
    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        await test_session.execute(
            text("""
                INSERT INTO edi_messages
                (id, trace_id, tenant_id, sender_id, receiver_id, direction, format_standard, transaction_type, status, edi_data, is_resend)
                VALUES (:id, :id, :tenant_id, 'partner', 'soopa', 'INBOUND', 'X12', '850', 'RECEIVED', 'test_data', false)
            """),
            {"id": trace_id, "tenant_id": tenant_id},
        )
        await test_session.commit()

    # 2. Setup Registries and Dispatchers
    registry = EdiDataPlaneRouteRegistry()
    settings = get_settings()
    transformer = BotsTransformerAdapter()

    # Simple factory representing the actual Orchestrator wiring
    @contextlib.asynccontextmanager
    async def uow_factory():
        async for session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
            await session.execute(
                text(f"SELECT set_config('app.current_tenant', '{tenant_id}', true)")
            )
            yield SqlAlchemyDataPlaneUnitOfWork(
                session=session, settings=settings, storage=transformer
            )
            break

    async def run_inbound(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        async with uow_fact() as uow:
            await DispatchInboundTransformUseCase(uow, transformer, settings).execute(e.trace_id)

    registry.register(
        event_type=PipelineEventType.TRANSFORM_EVENT.value,
        direction="INBOUND",
        factory=run_inbound,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        await registry.route(event, uow_factory)

    dispatcher = EdiDataPlaneEventDispatcher(callback=route_event)

    # 3. Emulate SQS Consumer feeding the dispatcher
    sqs_body = {
        "tenant_id": tenant_id,
        "idempotency_key": "some_key",
        "event_type": PipelineEventType.TRANSFORM_EVENT.value,
        "payload": {"trace_id": trace_id, "direction": "INBOUND"},
    }

    # Execute the state machine transition
    await dispatcher.handle(sqs_body)

    # 4. Verify Database State Machine Outbox Event
    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        result = await test_session.execute(
            text("SELECT payload, event_type FROM outbox WHERE payload->>'trace_id' = :trace_id"),
            {"trace_id": trace_id},
        )
        outbox_events = result.mappings().all()

    assert len(outbox_events) == 1, (
        "Expected exactly 1 outbox event to be produced by the state machine transition"
    )

    outbox_event = outbox_events[0]
    assert outbox_event["event_type"] == PipelineEventType.COMPUTE_TRANSFORM_EVENT.value
    payload = outbox_event["payload"]
    assert payload["direction"] == "INBOUND"
    assert payload["standard"] == "X12"
    assert payload["transaction_type"] == "850"
    assert payload["tenant_id"] == tenant_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_inbound_webhook_dispatch_transition(
    db_router: TransactionalTestRouter, httpserver: HTTPServer
) -> None:
    # 1. Setup DB Data
    tenant_id = f"ten_orch_web_{generate_random_hex(6)}"
    trace_id = f"trace_web_{generate_random_hex(6)}"
    webhook_id = f"webhook_{generate_random_hex(6)}"
    route_id = f"route_{generate_random_hex(6)}"

    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) VALUES (:id, 'Test', :slug, 'active', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"orch-web-{generate_random_hex(6)}"},
    )

    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        # Insert EDI message
        await test_session.execute(
            text("""
                INSERT INTO edi_messages
                (id, trace_id, tenant_id, sender_id, receiver_id, direction, format_standard, transaction_type, status, edi_data, is_resend)
                VALUES (:id, :id, :tenant_id, 'sender1', 'receiver1', 'INBOUND', 'X12', '850', 'TRANSFORMED', 'test_data', false)
            """),
            {"id": trace_id, "tenant_id": tenant_id},
        )
        webhook_target_url = httpserver.url_for("/webhook")
        # Insert API Payload (used by webhook strategy)
        await test_session.execute(
            text("""
                INSERT INTO api_gateway (id, trace_id, tenant_id, payload, status, webhook_url, direction, transaction_type, created_at, updated_at)
                VALUES (:id, :trace_id, :tenant_id, '{"payload": {"hello": "world"}}'::jsonb, 'PENDING_DELIVERY', :url, 'INBOUND', '850', NOW(), NOW())
            """),
            {
                "id": f"api_{generate_random_hex(6)}",
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "url": webhook_target_url,
            },
        )
        # Insert Webhook destination
        await test_session.execute(
            text("""
                INSERT INTO webhooks (id, tenant_id, name, url, active, created_at, updated_at)
                VALUES (:id, :tenant_id, 'Test Hook', :url, true, NOW(), NOW())
            """),
            {"id": webhook_id, "tenant_id": tenant_id, "url": webhook_target_url},
        )
        # Insert Route
        await test_session.execute(
            text("""
                INSERT INTO inbound_routes
                (id, tenant_id, name, isa_sender_id, isa_receiver_id, transaction_type, processing_mode, active, webhook_id, created_at, updated_at)
                VALUES (:id, :tenant_id, 'Test Route', 'sender1', 'receiver1', '850', 'TRANSFORM', true, :webhook_id, NOW(), NOW())
            """),
            {"id": route_id, "tenant_id": tenant_id, "webhook_id": webhook_id},
        )
        await test_session.commit()

    # 2. Setup Delivery Router Use Case inside Orchestrator
    # Serve a local endpoint on a real socket to capture the webhook
    httpserver.expect_request("/webhook", method="POST").respond_with_json({"status": "ok"})

    registry = EdiDataPlaneRouteRegistry()
    settings = get_settings()
    # Use real HTTPX client instead of AsyncMock
    real_http_delivery = HttpxDeliveryClient(allow_private_ips=True)

    @contextlib.asynccontextmanager
    async def uow_factory():
        async for session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
            await session.execute(
                text(f"SELECT set_config('app.current_tenant', '{tenant_id}', true)")
            )
            # We don't have a fake storage, use the real Transformer adapter
            # or just leave it empty if not used by WebhookDeliveryStrategy
            yield SqlAlchemyDataPlaneUnitOfWork(
                session=session, settings=settings, storage=BotsTransformerAdapter()
            )
            break

    async def run_delivery(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        async with uow_fact() as uow:
            strategies = {"webhook_id": WebhookDeliveryStrategy(uow, real_http_delivery)}
            await DeliveryRouterUseCase(uow, strategies).deliver(e.trace_id)
            await uow.commit()

    registry.register(
        event_type=PipelineEventType.TRANSFORM_COMPLETED.value,
        direction="INBOUND",
        factory=run_delivery,
    )

    dispatcher = EdiDataPlaneEventDispatcher(
        callback=lambda event: registry.route(event, uow_factory)
    )

    # 3. Simulate SQS payload for TRANSFORM_COMPLETED
    sqs_body = {
        "tenant_id": tenant_id,
        "idempotency_key": "some_key_123",
        "event_type": PipelineEventType.TRANSFORM_COMPLETED.value,
        "payload": {"trace_id": trace_id, "direction": "INBOUND"},
    }

    await dispatcher.handle(sqs_body)

    # 4. Verify Delivery Success Outbox Event was written
    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        result = await test_session.execute(
            text("SELECT payload, event_type FROM outbox WHERE payload->>'trace_id' = :trace_id"),
            {"trace_id": trace_id},
        )
        outbox_events = result.mappings().all()

    # WebhookDeliveryStrategy produces a DELIVERY_COMPLETED_EVENT
    delivery_events = [
        e for e in outbox_events if e["event_type"] == PipelineEventType.DELIVERY_COMPLETED.value
    ]
    assert len(delivery_events) == 1, "Expected DELIVERY_COMPLETED"

    # Verify Http request was made successfully against our local HTTPServer
    httpserver.check_assertions()
    # Assuming only one request was made to /webhook
    assert len(httpserver.log) == 1
    req, _ = httpserver.log[0]
    assert req.method == "POST"

    # Verify API Gateway Status updated
    async for test_session in db_router.get_shard_session("ucp_shard_1", "mock_dsn"):
        result = await test_session.execute(
            text("SELECT status FROM api_gateway WHERE trace_id = :id"), {"id": trace_id}
        )
        status = result.scalar_one()
        assert status == "DELIVERED"
