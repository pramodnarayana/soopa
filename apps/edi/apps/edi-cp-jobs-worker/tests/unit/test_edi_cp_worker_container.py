"""Unit tests for EDI Control Plane Jobs Worker OutboxDrainRelay wiring."""

from __future__ import annotations

import pytest
from edi.domain.enums import EdiOutboxSource
from outbox.adapters.inbound.outbox_drain_relay import OutboxDrainRelay
from outbox.testing.fakes import FakeOutboxPublisher, FakeOutboxRepository

from edi_cp_jobs_worker.bootstrap.container import WorkerContainer


@pytest.mark.asyncio
async def test_edi_cp_worker_container_wires_outbox_drain_relay() -> None:
    container = WorkerContainer()
    try:
        container._wire_outbox_relay(FakeOutboxRepository(), FakeOutboxPublisher())
        assert isinstance(container.cp_outbox_relay, OutboxDrainRelay)
        assert container.cp_outbox_relay.relay_name == EdiOutboxSource.EDI_CONTROL_PLANE.value
    finally:
        await container.dispose()
