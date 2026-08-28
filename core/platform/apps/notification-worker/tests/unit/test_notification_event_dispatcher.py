import pytest
from notification.domain.models import NotificationEvent

from notification_worker.adapters.inbound.workers.notification_event_dispatcher import (
    NotificationEventDispatcher,
)


class FakeDispatchUseCase:
    def __init__(self):
        self.events = []

    async def execute(self, event: NotificationEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_dispatcher_process_message_valid():
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body = {
        "event_type": "notification.requested",
        "payload": {
            "event": {
                "event_type": "invoice.paid",
                "tenant_id": "t1",
                "data": {"foo": "bar"},
                "source": "billing",
            }
        },
    }

    await dispatcher.dispatch(body)

    assert len(use_case.events) == 1
    event = use_case.events[0]
    assert event.event_type == "invoice.paid"
    assert event.tenant_id == "t1"
    assert event.data == {"foo": "bar"}
    assert event.source == "billing"


@pytest.mark.asyncio
async def test_dispatcher_ignores_other_events():
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body = {
        "event_type": "some.other.event",
        "payload": {},
    }

    await dispatcher.dispatch(body)
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_dispatcher_handles_missing_payload():
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body = {
        "event_type": "notification.requested",
    }

    # Should ignore or fail gracefully
    await dispatcher.dispatch(body)
    assert len(use_case.events) == 0
