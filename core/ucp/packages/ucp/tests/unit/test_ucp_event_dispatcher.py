from typing import Any

import pytest

from ucp.adapters.inbound.workers.ucp_event_dispatcher import UcpEventDispatcher
from ucp.ports.outbound.ucp_event_consumer_port import UcpEventMessage


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"event_type": "tenant.created", "tenant_id": "tenant-1", "payload": {}},
        {"id": "event-1", "tenant_id": "tenant-1", "payload": {}},
        {"id": "event-1", "event_type": "tenant.created", "payload": {}},
        {
            "id": "event-1",
            "event_type": "tenant.created",
            "tenant_id": "tenant-1",
            "payload": [],
        },
    ],
)
async def test_dispatch_rejects_malformed_envelopes(payload: dict[str, Any]) -> None:
    dispatcher = UcpEventDispatcher()

    with pytest.raises(ValueError, match="event envelope"):
        await dispatcher.dispatch(payload)


@pytest.mark.asyncio
async def test_dispatch_accepts_valid_envelope() -> None:
    dispatcher = UcpEventDispatcher()
    received: list[UcpEventMessage] = []

    async def handler(event: UcpEventMessage) -> None:
        received.append(event)

    dispatcher.subscribe("tenant.created", handler)

    await dispatcher.dispatch(
        {
            "id": "event-1",
            "event_type": "tenant.created",
            "tenant_id": "tenant-1",
            "payload": {"name": "Example"},
        }
    )

    assert len(received) == 1
    assert received[0].id == "event-1"
    assert received[0].payload == {"name": "Example"}
