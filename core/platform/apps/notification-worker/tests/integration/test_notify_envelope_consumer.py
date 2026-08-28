from dataclasses import asdict
from unittest.mock import AsyncMock

import pytest
from notification.domain.models import NotificationEvent
from notification.facade import notify


class RecordingCompiler:
    def __init__(self) -> None:
        self.events: list[NotificationEvent] = []

    async def execute(self, event: NotificationEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_notify_envelope_consumed() -> None:
    envelope = notify(
        tenant_id="tenant-1",
        source="edi",
        domain_event_type="invoice.failed",
        payload={"invoice_id": "invoice-1", "event_type": "payload.decoy"},
    )
    compiler = RecordingCompiler()
    cleanup_mock = AsyncMock()

    from notification_worker.adapters.inbound.workers.notification_event_dispatcher import (
        NotificationEventDispatcher,
    )

    dispatcher = NotificationEventDispatcher(
        notification_compiler=compiler, cleanup_job_handler=cleanup_mock
    )
    await dispatcher.dispatch_raw(asdict(envelope))

    assert len(compiler.events) == 1
    processed_event = compiler.events[0]
    assert processed_event.tenant_id == "tenant-1"
    assert processed_event.event_type == "invoice.failed"
    assert processed_event.data["invoice_id"] == "invoice-1"
