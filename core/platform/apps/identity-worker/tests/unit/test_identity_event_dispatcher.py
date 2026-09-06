from collections.abc import Generator

import pytest
from identity_worker.adapters.inbound.workers.identity_event_dispatcher import (
    IdentityEventDispatcher,
)
from identity_worker.ports.inbound.identity_event_consumer_port import IdentityEventMessage


class CustomAwaitable:
    def __init__(self) -> None:
        self.awaited = False

    def __await__(self) -> Generator[None, None, None]:
        self.awaited = True
        if False:
            yield
        return None


@pytest.mark.asyncio
async def test_dispatch_awaits_custom_awaitable_handler_result() -> None:
    dispatcher = IdentityEventDispatcher()
    result = CustomAwaitable()

    def handler(_event: IdentityEventMessage) -> CustomAwaitable:
        return result

    dispatcher.subscribe("user.created", handler)
    event = IdentityEventMessage(
        id="evt_1",
        source="identity",
        event_type="user.created",
        payload={},
        idempotency_key=None,
        tenant_id="ten_1",
    )

    await dispatcher._dispatch(event)

    assert result.awaited is True
