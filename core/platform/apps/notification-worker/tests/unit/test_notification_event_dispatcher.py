import pytest
from notification.application.notification_compiler_use_case import CompileNotificationCommand
from notification.domain.constants import NotificationEventType
from seedwork.domain.types import JsonDict, JsonValue

from notification_worker.adapters.inbound.workers.notification_event_dispatcher import (
    NotificationEventDispatcher,
)


class FakeDispatchUseCase:
    def __init__(self) -> None:
        self.events: list[CompileNotificationCommand] = []

    async def execute(self, event: CompileNotificationCommand) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_dispatcher_process_message_valid() -> None:
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    raw_notification_data: JsonDict = {"foo": "bar"}
    body: JsonDict = {
        "id": "sys_gen_env_001",
        "idempotency_key": "step_run_1:notify_ops:0",
        "event_type": NotificationEventType.NOTIFICATION_TRIGGERED.value,
        "tenant_id": "t1",
        "payload": {
            "notification_type": "invoice.paid",
            "notification_data": raw_notification_data,
            "source": "billing",
        },
    }

    await dispatcher.dispatch_raw(body)

    assert len(use_case.events) == 1
    event = use_case.events[0]
    assert event.event_type == "invoice.paid"
    assert event.tenant_id == "t1"
    assert event.idempotency_key == "step_run_1:notify_ops:0"
    assert event.data == {"foo": "bar", "tenant_id": "t1"}
    assert "tenant_id" not in raw_notification_data


@pytest.mark.asyncio
async def test_dispatcher_falls_back_to_envelope_id_when_idempotency_key_missing() -> None:
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body: JsonDict = {
        "id": "sys_gen_env_fallback_99",
        "event_type": NotificationEventType.NOTIFICATION_TRIGGERED.value,
        "tenant_id": "t1",
        "payload": {
            "notification_type": "invoice.paid",
            "notification_data": {"foo": "bar"},
        },
    }

    await dispatcher.dispatch_raw(body)

    assert len(use_case.events) == 1
    assert use_case.events[0].idempotency_key == "sys_gen_env_fallback_99"


@pytest.mark.asyncio
async def test_dispatcher_ignores_other_events() -> None:
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body: JsonDict = {
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
async def test_dispatcher_rejects_numeric_top_level_tenant_id() -> None:
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(
        notification_compiler=use_case,
    )

    body: JsonDict = {
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
async def test_dispatcher_rejects_non_string_notification_type(
    notification_type: JsonValue,
) -> None:
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(
        notification_compiler=use_case,
    )

    body: JsonDict = {
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
async def test_dispatcher_handles_missing_payload() -> None:
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(notification_compiler=use_case)

    body: JsonDict = {
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
async def test_dispatcher_rejects_non_dictionary_nested_objects(body: JsonDict) -> None:
    use_case = FakeDispatchUseCase()
    dispatcher = NotificationEventDispatcher(
        notification_compiler=use_case,
    )

    await dispatcher.dispatch_raw(body)

    assert use_case.events == []
