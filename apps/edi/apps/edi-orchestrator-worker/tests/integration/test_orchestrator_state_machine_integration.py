import contextlib
import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest
from pubsub.testing.in_memory_event_bus import InMemoryEventBus

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
from database.testing import TransactionalTestRouter
from edi.adapters.outbound.database.data_plane.uow import SqlAlchemyDataPlaneUnitOfWork
from edi.adapters.outbound.pipeline.transformer import BotsTransformerAdapter
from edi.application.use_cases.pipeline.delivery_router_use_case import DeliveryRouterUseCase
from edi.application.use_cases.pipeline.dispatch_inbound_transform_use_case import (
    DispatchInboundTransformUseCase,
)
from edi.application.use_cases.pipeline.dispatch_outbound_transform_use_case import (
    DispatchOutboundTransformUseCase,
)
from edi.domain.enums import PipelineEventType
from seedwork import generate_random_hex
from seedwork.events import EventEnvelope
from sqlalchemy import text

from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry
from worker.settings import get_settings


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
    async for test_session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
        await test_session.execute(
            text("""
                INSERT INTO edi_messages
                (id, trace_id, tenant_id, sender_id, receiver_id, direction, format_standard, transaction_type, status, edi_data, replay_count)
                VALUES (:id, :id, :tenant_id, 'partner', 'soopa', 'INBOUND', 'X12', '850', 'RECEIVED', 'test_data', 0)
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
        async for session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
            await session.execute(
                text(f"SELECT set_config('platform.current_tenant_id', '{tenant_id}', true)")
            )
            yield SqlAlchemyDataPlaneUnitOfWork(tenant_session=session, storage=transformer)
            break

    async def run_inbound(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        fake_publisher = InMemoryEventBus()
        await DispatchInboundTransformUseCase(
            uow_fact, transformer, settings, fake_publisher
        ).execute(e.trace_id, idempotency_key=e.idempotency_key)

    registry.register(
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        direction="INBOUND",
        factory=run_inbound,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        await registry.route(event, uow_factory)

    dispatcher = EdiDataPlaneEventDispatcher(callback=route_event)

    # 3. Emulate SQS Consumer feeding the dispatcher
    sqs_body = EventEnvelope(
        id="test-msg-1",
        source="test",
        tenant_id=tenant_id,
        idempotency_key="some_key",
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        payload={"trace_id": trace_id, "direction": "INBOUND"},
    )

    # Execute the state machine transition
    await dispatcher.handle(dataclasses.asdict(sqs_body))

    # 4. Verify Database State Machine Outbox Event
    async for test_session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
        result = await test_session.execute(
            text("SELECT payload, event_type FROM outbox WHERE payload->>'trace_id' = :trace_id"),
            {"trace_id": trace_id},
        )
        outbox_events = result.mappings().all()

    assert len(outbox_events) == 1, (
        "Expected exactly 1 outbox event to be produced by the state machine transition"
    )

    outbox_event = outbox_events[0]
    assert outbox_event["event_type"] == PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value
    payload = outbox_event["payload"]
    assert payload["direction"] == "INBOUND"
    assert payload["standard"] == "X12"
    assert payload["transaction_type"] == "850"
    assert payload["tenant_id"] == tenant_id


async def test_inbound_webhook_dispatch_transition(db_router: TransactionalTestRouter) -> None:
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

    async for test_session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
        # Insert EDI message
        await test_session.execute(
            text("""
                INSERT INTO edi_messages
                (id, trace_id, tenant_id, sender_id, receiver_id, direction, format_standard, transaction_type, status, edi_data, replay_count)
                VALUES (:id, :id, :tenant_id, 'sender1', 'receiver1', 'INBOUND', 'X12', '850', 'TRANSFORMED', 'test_data', 0)
            """),
            {"id": trace_id, "tenant_id": tenant_id},
        )
        webhook_target_url = "https://example.com/webhook"
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
                (id, tenant_id, name, isa_sender_id, isa_receiver_id, transaction_type, processing_mode, active, webhook_id, connection_type, created_at, updated_at)
                VALUES (:id, :tenant_id, 'Test Route', 'sender1', 'receiver1', '850', 'TRANSFORM', true, :webhook_id, 'WEBHOOK', NOW(), NOW())
            """),
            {"id": route_id, "tenant_id": tenant_id, "webhook_id": webhook_id},
        )
        await test_session.commit()

    registry = EdiDataPlaneRouteRegistry()

    @contextlib.asynccontextmanager
    async def uow_factory():
        async for session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
            await session.execute(
                text(f"SELECT set_config('platform.current_tenant_id', '{tenant_id}', true)")
            )
            # We don't have a fake storage, use the real Transformer adapter
            # or just leave it empty if not used by WebhookDeliveryStrategy
            yield SqlAlchemyDataPlaneUnitOfWork(
                tenant_session=session, storage=BotsTransformerAdapter()
            )
            break

    async def run_delivery(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        async with uow_fact() as uow:

            def mock_uow_factory():
                @contextlib.asynccontextmanager
                async def mock_manager():
                    yield uow

                return mock_manager()

            fake_publisher = InMemoryEventBus()
            await DeliveryRouterUseCase(mock_uow_factory, fake_publisher).deliver(
                trace_id=e.trace_id, idempotency_key=e.idempotency_key
            )
            await uow.commit()

    registry.register(
        event_type=PipelineEventType.TRANSFORMATION_SUCCESSFUL.value,
        direction="INBOUND",
        factory=run_delivery,
    )

    dispatcher = EdiDataPlaneEventDispatcher(
        callback=lambda event: registry.route(event, uow_factory)
    )

    # 3. Simulate SQS payload for TRANSFORMATION_COMPLETED
    sqs_body = EventEnvelope(
        id="test-msg-2",
        source="test",
        tenant_id=tenant_id,
        idempotency_key="some_key_123",
        event_type=PipelineEventType.TRANSFORMATION_SUCCESSFUL.value,
        payload={"trace_id": trace_id, "direction": "INBOUND"},
    )

    await dispatcher.handle(dataclasses.asdict(sqs_body))

    # 4. Verify Delivery Success Outbox Event was written
    async for test_session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
        result = await test_session.execute(
            text("SELECT payload, event_type FROM outbox WHERE payload->>'trace_id' = :trace_id"),
            {"trace_id": trace_id},
        )
        outbox_events = result.mappings().all()

    delivery_commands = [
        e
        for e in outbox_events
        if e["event_type"] == PipelineEventType.EXECUTE_DELIVERY_COMMAND.value
    ]
    assert len(delivery_commands) == 1, "Expected EXECUTE_DELIVERY_COMMAND"
    payload = delivery_commands[0]["payload"]
    assert payload["strategy_type"] == "webhook_id"
    assert payload["partner_id"] == webhook_id


async def test_outbound_routing_state_machine_transition(
    db_router: TransactionalTestRouter,
) -> None:
    """
    Verifies that a TRANSFORMATION_REQUESTED (OUTBOUND) event received by the
    Orchestrator results in a COMPUTE_TRANSFORMATION_COMMAND being written to
    the outbox, containing the correct EDI envelope headers resolved from the
    tenant's outbound route and EDI headers.

    Pipeline step under test:
        API → [TRANSFORMATION_REQUESTED OUTBOUND] → Orchestrator
            → [COMPUTE_TRANSFORMATION_COMMAND] → Compute Worker
    """
    # 1. Seed DB fixtures
    tenant_id = f"ten_ob_{generate_random_hex(6)}"
    trace_id = f"trace_ob_{generate_random_hex(6)}"
    trading_partner_id = f"tp_{generate_random_hex(6)}"
    as2_partner_id = f"as2_{generate_random_hex(6)}"

    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, idp_tenant_id, created_at, updated_at) "
            "VALUES (:id, 'OutboundTest', :slug, 'active', 'idp_ob', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"ob-{generate_random_hex(6)}"},
    )

    async for test_session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
        # AS2 partner (needed by outbound_routes FK)
        await test_session.execute(
            text("""
                INSERT INTO as2_partners
                (id, tenant_id, name, as2_id, url, active, created_at, updated_at)
                VALUES (:id, :tenant_id, 'Test AS2 Partner', 'PARTNER_AS2', 'https://as2.example.com', true, NOW(), NOW())
            """),
            {"id": as2_partner_id, "tenant_id": tenant_id},
        )
        # Outbound route linked to the trading partner and AS2 partner
        await test_session.execute(
            text("""
                INSERT INTO outbound_routes
                (id, tenant_id, name, trading_partner_id, active, connection_type, as2_partner_id, created_at, updated_at)
                VALUES (:id, :tenant_id, 'Test Outbound Route', :tp_id, true, 'AS2', :as2_id, NOW(), NOW())
            """),
            {
                "id": f"ob_route_{generate_random_hex(6)}",
                "tenant_id": tenant_id,
                "tp_id": trading_partner_id,
                "as2_id": as2_partner_id,
            },
        )
        # EDI headers for the trading partner (transaction_type and environment live here)
        await test_session.execute(
            text("""
                INSERT INTO outbound_edi_headers
                (id, tenant_id, trading_partner_id, name, isa_sender_id, isa_receiver_id, gs_sender_id, gs_receiver_id, transaction_type, default_standard, created_at, updated_at)
                VALUES (:id, :tenant_id, :tp_id, 'Test Headers', 'SENDER01', 'RECEIVER01', 'GS_SENDER', 'GS_RECV', '850', 'x12', NOW(), NOW())
            """),
            {
                "id": f"hdr_{generate_random_hex(6)}",
                "tenant_id": tenant_id,
                "tp_id": trading_partner_id,
            },
        )
        # edi_json record — the JSON payload to be transformed
        await test_session.execute(
            text("""
                INSERT INTO edi_json
                (id, trace_id, tenant_id, trading_partner_id, payload, status, direction, transaction_type, created_at, updated_at)
                VALUES (:id, :trace_id, :tenant_id, :tp_id, :payload, 'PENDING', 'OUTBOUND', '850', NOW(), NOW())
            """),
            {
                "id": f"json_{generate_random_hex(6)}",
                "trace_id": trace_id,
                "tenant_id": tenant_id,
                "tp_id": trading_partner_id,
                "payload": json.dumps({"PO1": {"PO101": "1"}}),
            },
        )
        await test_session.commit()

    # 2. Wire up the registry, UoW factory, and dispatcher
    registry = EdiDataPlaneRouteRegistry()
    settings = get_settings()
    transformer = BotsTransformerAdapter()

    @contextlib.asynccontextmanager
    async def uow_factory():
        async for session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
            await session.execute(
                text(f"SELECT set_config('platform.current_tenant_id', '{tenant_id}', true)")
            )
            yield SqlAlchemyDataPlaneUnitOfWork(tenant_session=session, storage=transformer)
            break

    async def run_outbound(e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]) -> None:
        fake_publisher = InMemoryEventBus()
        await DispatchOutboundTransformUseCase(
            uow_fact, transformer, settings, fake_publisher
        ).execute(e.trace_id, idempotency_key=e.idempotency_key)

    registry.register(
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        direction="OUTBOUND",
        factory=run_outbound,
    )

    dispatcher = EdiDataPlaneEventDispatcher(
        callback=lambda event: registry.route(event, uow_factory)
    )

    # 3. Simulate SQS payload arriving at the Orchestrator
    sqs_body = EventEnvelope(
        id="test-ob-msg-1",
        source="test",
        tenant_id=tenant_id,
        idempotency_key=f"idemp_{generate_random_hex(8)}",
        event_type=PipelineEventType.TRANSFORMATION_REQUESTED.value,
        payload={"trace_id": trace_id, "direction": "OUTBOUND"},
    )
    await dispatcher.handle(dataclasses.asdict(sqs_body))

    # 4. Assert COMPUTE_TRANSFORMATION_COMMAND outbox event was written with correct EDI headers
    async for test_session in db_router.get_shard_session("ucp_shard_1", "fake_dsn"):
        result = await test_session.execute(
            text("SELECT payload, event_type FROM outbox WHERE payload->>'trace_id' = :trace_id"),
            {"trace_id": trace_id},
        )
        outbox_events = result.mappings().all()

    compute_commands = [
        e
        for e in outbox_events
        if e["event_type"] == PipelineEventType.COMPUTE_TRANSFORMATION_COMMAND.value
    ]
    assert len(compute_commands) == 1, "Expected exactly 1 COMPUTE_TRANSFORMATION_COMMAND in outbox"

    payload = compute_commands[0]["payload"]
    assert payload["direction"] == "OUTBOUND"
    assert payload["isa_sender_id"] == "SENDER01"
    assert payload["isa_receiver_id"] == "RECEIVER01"
    assert payload["gs_sender_id"] == "GS_SENDER"
    assert payload["gs_receiver_id"] == "GS_RECV"
    assert payload["isa_usage_indicator"] == "T"
    assert payload["tenant_id"] == tenant_id
    assert payload["trace_id"] == trace_id
