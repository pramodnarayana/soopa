import pytest
from pubsub.dispatcher import DispatchKey, MessageDispatcher
from seedwork.domain.types import JsonDict
from seedwork.events import EventEnvelope


@pytest.mark.asyncio
async def test_message_dispatcher_subscribe_and_dispatch_dict() -> None:
    dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME)
    received: list[JsonDict] = []

    async def handle_job(msg: JsonDict) -> None:
        received.append(msg)

    dispatcher.subscribe("sync_tenants", handle_job)

    payload: JsonDict = {"job_name": "sync_tenants", "data": 123}
    await dispatcher.dispatch(payload)

    assert len(received) == 1
    assert received[0]["data"] == 123


@pytest.mark.asyncio
async def test_message_dispatcher_dispatch_with_event_envelope() -> None:
    dispatcher = MessageDispatcher(dispatch_key=DispatchKey.EVENT_TYPE)
    received: list[EventEnvelope] = []

    async def handle_event(msg: EventEnvelope) -> None:
        received.append(msg)

    dispatcher.subscribe("tenant.created", handle_event)

    envelope = EventEnvelope(
        id="evt_123",
        source="test",
        event_type="tenant.created",
        tenant_id="t_1",
        idempotency_key="ik_1",
        payload={"name": "Acme"},
    )
    await dispatcher.dispatch(envelope)

    assert len(received) == 1
    assert received[0].id == "evt_123"


@pytest.mark.asyncio
async def test_message_dispatcher_unknown_key_raises_value_error() -> None:
    dispatcher = MessageDispatcher(dispatch_key=DispatchKey.JOB_NAME)

    with pytest.raises(ValueError, match="Unknown value for 'job_name'"):
        await dispatcher.dispatch({"job_name": "unregistered_job"})
