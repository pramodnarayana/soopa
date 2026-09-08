import pytest
from notification.application.notification_compiler_use_case import CompileNotificationCommand
from notification.domain.constants import NotificationEventType

from notification_worker.adapters.inbound.workers.notification_event_dispatcher import (
    NotificationEventDispatcher,
)


class FakeDispatchUseCase:
    def __init__(self):
        self.events = []

    async def execute(self, event: CompileNotificationCommand) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_dispatcher_process_message_valid():
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body = {
        "event_type": NotificationEventType.NOTIFICATION_TRIGGERED.value,
        "tenant_id": "t1",
        "payload": {
            "notification_type": "invoice.paid",
            "notification_data": {"foo": "bar"},
            "source": "billing",
        },
    }

    await dispatcher.dispatch_raw(body)

    assert len(use_case.events) == 1
    event = use_case.events[0]
    assert event.event_type == "invoice.paid"
    assert event.tenant_id == "t1"
    assert event.data == {"foo": "bar", "tenant_id": "t1"}


@pytest.mark.asyncio
async def test_dispatcher_ignores_other_events():
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body = {
        "event_type": "some.other.event",
        "tenant_id": "t1",
        "payload": {
            "notification_type": "invoice.paid",
            "notification_data": {"foo": "bar"},
        },
    }

    await dispatcher.dispatch_raw(body)
    assert len(use_case.events) == 0


@pytest.mark.asyncio
async def test_dispatcher_rejects_numeric_top_level_tenant_id():
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(
        notification_compiler=use_case,
    )

    body = {
        "event_type": NotificationEventType.NOTIFICATION_TRIGGERED.value,
        "tenant_id": 123,
        "payload": {
            "notification_type": "invoice.paid",
            "notification_data": {"foo": "bar"},
        },
    }

    await dispatcher.dispatch_raw(body)

    assert use_case.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("notification_type", [123, ["invoice.paid"]])
async def test_dispatcher_rejects_non_string_notification_type(notification_type):
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(
        notification_compiler=use_case,
    )

    body = {
        "event_type": NotificationEventType.NOTIFICATION_TRIGGERED.value,
        "tenant_id": "t1",
        "payload": {
            "notification_type": notification_type,
            "notification_data": {"foo": "bar"},
        },
    }

    await dispatcher.dispatch_raw(body)

    assert use_case.events == []


@pytest.mark.asyncio
async def test_dispatcher_handles_missing_payload():
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body = {
        "event_type": NotificationEventType.NOTIFICATION_TRIGGERED.value,
        # no payload
    }

    await dispatcher.dispatch_raw(body)
    assert len(use_case.events) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {
            "event_type": NotificationEventType.NOTIFICATION_TRIGGERED.value,
            "payload": "invalid",
        },
        {
            "event_type": NotificationEventType.NOTIFICATION_TRIGGERED.value,
            "payload": {"notification_data": "invalid"},
        },
    ],
)
async def test_dispatcher_rejects_non_dictionary_nested_objects(body):
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(
        notification_compiler=use_case,
    )

    await dispatcher.dispatch_raw(body)

    assert use_case.events == []
