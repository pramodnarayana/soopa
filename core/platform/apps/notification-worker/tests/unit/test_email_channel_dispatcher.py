import pytest

from notification_worker.adapters.inbound.workers.email_channel_dispatcher import (
    EmailChannelDispatcher,
)


class FakeEmailStrategy:
    def __init__(self):
        self.delivered = []
        self.should_fail = False

    async def deliver(self, tenant_id: str, content: str, subject: str | None, data: dict) -> None:
        if self.should_fail:
            raise RuntimeError("Delivery failed")
        self.delivered.append(
            {"tenant_id": tenant_id, "content": content, "subject": subject, "data": data}
        )


@pytest.mark.asyncio
async def test_email_dispatcher_success():
    strategy = FakeEmailStrategy()
    dispatcher = EmailChannelDispatcher(email_strategy=strategy)

    body = {
        "event_type": "email.requested",
        "tenant_id": "tenant-1",
        "idempotency_key": "idempotency_key",
        "payload": {
            "tenant_id": "tenant-1",
            "content": "Hello",
            "subject": "Subj",
            "data": {"foo": "bar"},
        },
    }

    await dispatcher.dispatch_raw(body)

    assert len(strategy.delivered) == 1
    call = strategy.delivered[0]
    assert call["tenant_id"] == "tenant-1"
    assert call["content"] == "Hello"
    assert call["subject"] == "Subj"
    assert call["data"] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_email_dispatcher_failure_propagates():
    strategy = FakeEmailStrategy()
    strategy.should_fail = True
    dispatcher = EmailChannelDispatcher(email_strategy=strategy)

    body = {
        "event_type": "email.requested",
        "tenant_id": "tenant-1",
        "idempotency_key": "idempotency_key",
        "payload": {"tenant_id": "tenant-1", "content": "Hello", "subject": "Subj", "data": {}},
    }

    with pytest.raises(RuntimeError, match="Delivery failed"):
        await dispatcher.dispatch_raw(body)


@pytest.mark.asyncio
async def test_email_dispatcher_ignores_other_events():
    strategy = FakeEmailStrategy()
    dispatcher = EmailChannelDispatcher(email_strategy=strategy)

    body = {
        "event_type": "some.other.event",
        "tenant_id": "tenant-1",
        "idempotency_key": "idempotency_key",
        "payload": {},
    }

    await dispatcher.dispatch_raw(body)
    assert len(strategy.delivered) == 0
