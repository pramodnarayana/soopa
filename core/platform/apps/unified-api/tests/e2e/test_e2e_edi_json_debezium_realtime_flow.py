from collections.abc import Callable
from typing import Any

import httpx
import pytest
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.domain.events import PipelineEventType
from sqlalchemy import select
from worker.adapters.inbound.workers.edi_data_plane_event_dispatcher import (
    EdiDataPlaneEventDispatcher,
    EdiDataPlaneEventMessage,
)
from worker.domain.edi_data_plane_route_registry import EdiDataPlaneRouteRegistry


# ---------------------------------------------------------------------------
# Helper: Simulate Debezium ExtractNewRecordState SMT
# ---------------------------------------------------------------------------
def simulate_debezium_unwrap_smt(outbox_row: DataPlaneOutbox) -> dict[str, Any]:
    """
    Simulates the exact JSON payload produced by Debezium Server 3.6 configured with:
    debezium.transforms=unwrap
    debezium.transforms.unwrap.type=io.debezium.transforms.ExtractNewRecordState

    Debezium drops the 'before'/'after' envelope and directly emits the 'after' state
    (the raw database row) as a JSON object, which is then routed via SNS -> SQS.
    """
    return {
        "id": str(outbox_row.id),
        "tenant_id": str(outbox_row.tenant_id),
        "event_type": outbox_row.event_type,
        # Debezium parses JSONB columns into nested JSON objects natively when schemas.enable=false
        "payload": outbox_row.payload,
        "idempotency_key": outbox_row.idempotency_key,
        "status": outbox_row.status,
        "created_at": outbox_row.created_at.isoformat() if outbox_row.created_at else None,
        "updated_at": outbox_row.updated_at.isoformat() if outbox_row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e2e_outbound_edi_json_debezium_realtime_flow(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
    db_session_factory: Any,
) -> None:
    """
    Tests the Realtime CDC Flow for Outbound EDI JSON:
    1. Unified API handles the ingress POST request and commits to the DB.
    2. Debezium reads the WAL and pushes the row to SNS -> SQS (simulated).
    3. Orchestrator Worker consumes the SQS message and dispatches the pipeline logic.
    """
    tenant_id = seeded_api_token["tenant_id"]

    # 1. HTTP Ingress (Unified API) -> DB
    payload = {
        "trading_partner_id": "tp_123",
        "transaction_type": "850",
        "payload": {"order": "123"},
    }
    response = await auth_client.post("/api/v1/edi_json", json=payload)
    assert response.status_code == 202, response.text
    trace_id = response.json()["trace_id"]

    # 2. Extract outbox event simulating the Debezium WAL capture
    async with db_session_factory() as session:
        outbox_result = await session.execute(
            select(DataPlaneOutbox)
            .where(DataPlaneOutbox.tenant_id == tenant_id)
            .order_by(DataPlaneOutbox.created_at.desc())
            .limit(1)
        )
        outbox_event = outbox_result.scalar_one_or_none()
        assert outbox_event is not None
        assert outbox_event.event_type == PipelineEventType.TRANSFORM_EVENT.value

        # Generate the Debezium SMT Payload
        debezium_payload = simulate_debezium_unwrap_smt(outbox_event)

    # 3. Process via Orchestrator Worker Dispatcher
    # We use a mock registry to verify routing occurs correctly for the INBOUND event
    processed_events = []

    async def mock_inbound_factory(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        processed_events.append(e)

    registry = EdiDataPlaneRouteRegistry()
    registry.register(
        event_type=PipelineEventType.TRANSFORM_EVENT.value,
        direction="OUTBOUND",
        factory=mock_inbound_factory,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        # Dummy UOW factory for the test
        async def dummy_uow_factory() -> Any:
            pass

        await registry.route(event, dummy_uow_factory)

    dispatcher = EdiDataPlaneEventDispatcher(callback=route_event)

    # Act: Pass the simulated Debezium payload into the worker's dispatcher
    await dispatcher.handle(debezium_payload)

    # Assert: The payload was successfully parsed and routed to the correct handler
    assert len(processed_events) == 1
    processed_event = processed_events[0]
    assert processed_event.trace_id == trace_id
    assert processed_event.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_e2e_inbound_debezium_realtime_flow(
    auth_client: httpx.AsyncClient,
    seeded_api_token: dict[str, Any],
    db_session_factory: Any,
) -> None:
    """
    Tests the Realtime CDC Flow for Inbound EDI:
    1. Unified API handles the inbound trigger (e.g. from webhook/API).
    2. Debezium reads the WAL and pushes the Inbound row to SNS -> SQS.
    3. Orchestrator Worker consumes the SQS message and dispatches it INBOUND.
    """
    tenant_id = seeded_api_token["tenant_id"]

    # 1. HTTP Ingress for Inbound (Unified API) -> DB
    # We manually insert the INBOUND Transform Event into the outbox to simulate the first step
    # of the Inbound pipeline, testing specifically the Debezium -> Orchestrator flow.
    trace_id = "trace_inbound_123"

    async with db_session_factory() as session:
        outbound_outbox = DataPlaneOutbox(
            tenant_id=tenant_id,
            event_type=PipelineEventType.TRANSFORM_EVENT.value,
            payload={"trace_id": trace_id, "direction": "INBOUND", "trading_partner_id": "tp_456"},
            status="PENDING",
            idempotency_key="idem_inbound_123",
        )
        session.add(outbound_outbox)
        await session.flush()

        # Capture exactly what Debezium would see
        debezium_payload = simulate_debezium_unwrap_smt(outbound_outbox)
        # Flush is enough because our test fixtures use savepoints, but we don't strictly need to commit
        # since we extract the row immediately into memory.

    # 3. Process via Orchestrator Worker Dispatcher
    processed_events = []

    async def mock_outbound_factory(
        e: EdiDataPlaneEventMessage, uow_fact: Callable[..., Any]
    ) -> None:
        processed_events.append(e)

    registry = EdiDataPlaneRouteRegistry()
    registry.register(
        event_type=PipelineEventType.TRANSFORM_EVENT.value,
        direction="INBOUND",
        factory=mock_outbound_factory,
    )

    async def route_event(event: EdiDataPlaneEventMessage) -> None:
        async def dummy_uow_factory() -> Any:
            pass

        await registry.route(event, dummy_uow_factory)

    dispatcher = EdiDataPlaneEventDispatcher(callback=route_event)

    # Act: Pass the simulated Debezium payload into the worker's dispatcher
    await dispatcher.handle(debezium_payload)

    # Assert: The payload was successfully parsed and routed to the INBOUND handler
    assert len(processed_events) == 1
    processed_event = processed_events[0]
    assert processed_event.trace_id == trace_id
    assert processed_event.tenant_id == tenant_id
    assert processed_event.payload["direction"] == "INBOUND"
