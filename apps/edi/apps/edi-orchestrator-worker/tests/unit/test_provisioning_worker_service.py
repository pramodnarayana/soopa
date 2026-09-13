from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from edi.domain.enums import EdiEventType
from identity.domain.identity_context import PLATFORM_TENANT_ID

from worker.domain.errors import PermanentProvisioningError, TransientProvisioningError
from worker.domain.service import ProvisioningWorkerService
from worker.ports.outbound.outbox_port import OutboxPort
from worker.ports.outbound.replication_port import ReplicationPort
from worker.ports.outbound.tenant_port import TenantPort


class FakeTenantPort(TenantPort):
    def __init__(self, tenant_ids: list[str]) -> None:
        self.tenant_ids = tenant_ids

    async def get_all_tenant_ids(self) -> list[str]:
        return self.tenant_ids

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        return "fake_shard", "fake_dsn"


@dataclass
class FakeOutboxEvent:
    id: str
    event_type: str
    body: dict[str, Any]


class FakeOutboxPort(OutboxPort):
    def __init__(self, events: list[FakeOutboxEvent]) -> None:
        self.events = events
        self.processed_events: list[FakeOutboxEvent] = []

    @asynccontextmanager
    async def process_next_event(self) -> AsyncGenerator[FakeOutboxEvent | None, None]:
        if not self.events:
            yield None
            return

        event = self.events.pop(0)
        yield event
        self.processed_events.append(event)


class FakeReplicationPort(ReplicationPort):
    def __init__(self) -> None:
        self.replicated_as2_partners: list[tuple[str, str]] = []
        self.deleted_as2_partners: list[tuple[str, str]] = []
        self.replicated_webhooks: list[tuple[str, str]] = []
        self.transient_fail_on_tenant: str | None = None
        self.permanent_fail_on_tenant: str | None = None

    async def replicate_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        if tenant_id == self.transient_fail_on_tenant:
            raise TransientProvisioningError("Fake transient error")
        if tenant_id == self.permanent_fail_on_tenant:
            raise PermanentProvisioningError("Fake permanent error")
        self.replicated_as2_partners.append((tenant_id, partner_id))

    async def delete_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        self.deleted_as2_partners.append((tenant_id, partner_id))

    async def replicate_webhook(self, tenant_id: str, webhook_id: str) -> None:
        self.replicated_webhooks.append((tenant_id, webhook_id))

    async def replicate_tenant_configuration(self, tenant_id: str) -> None:
        pass

    async def replicate_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        pass

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        pass

    async def replicate_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        pass

    async def delete_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        pass

    async def delete_webhook(self, tenant_id: str, webhook_id: str) -> None:
        pass

    async def replicate_inbound_route(self, tenant_id: str, route_id: str) -> None:
        pass

    async def delete_inbound_route(self, tenant_id: str, route_id: str) -> None:
        pass

    async def replicate_outbound_route(self, tenant_id: str, route_id: str) -> None:
        pass

    async def delete_outbound_route(self, tenant_id: str, route_id: str) -> None:
        pass

    async def replicate_outbound_edi_header(self, tenant_id: str, header_id: str) -> None:
        pass

    async def delete_outbound_edi_header(self, tenant_id: str, header_id: str) -> None:
        pass


@pytest.fixture
def fake_tenant_port() -> FakeTenantPort:
    return FakeTenantPort(["ten_1", "ten_2"])


@pytest.fixture
def fake_replication_port() -> FakeReplicationPort:
    return FakeReplicationPort()


@pytest.mark.asyncio
async def test_process_next_event_routes_to_replication(
    fake_tenant_port: FakeTenantPort,
    fake_replication_port: FakeReplicationPort,
) -> None:
    event = FakeOutboxEvent(
        id="evt_1",
        event_type=EdiEventType.edi_as2_partner_created.value,
        body={
            "tenant_id": "ten_1",
            "event_type": EdiEventType.edi_as2_partner_created.value,
            "resource_id": "partner_123",
            "idempotency_key": "ik_1",
        },
    )
    fake_outbox = FakeOutboxPort([event])
    service = ProvisioningWorkerService(fake_tenant_port, fake_outbox, fake_replication_port)

    processed = await service.process_next_event()
    assert processed is True
    assert fake_replication_port.replicated_as2_partners == [("ten_1", "partner_123")]
    assert len(fake_outbox.processed_events) == 1


@pytest.mark.asyncio
async def test_process_next_event_broadcasts_for_platform_tenant(
    fake_tenant_port: FakeTenantPort,
    fake_replication_port: FakeReplicationPort,
) -> None:
    event = FakeOutboxEvent(
        id="evt_1",
        event_type=EdiEventType.edi_as2_partner_created.value,
        body={
            "tenant_id": PLATFORM_TENANT_ID,
            "event_type": EdiEventType.edi_as2_partner_created.value,
            "resource_id": "platform_partner",
            "idempotency_key": "ik_1",
        },
    )
    fake_outbox = FakeOutboxPort([event])
    service = ProvisioningWorkerService(fake_tenant_port, fake_outbox, fake_replication_port)

    processed = await service.process_next_event()
    assert processed is True

    # Assert it was replicated to ALL tenants in the system
    assert set(fake_replication_port.replicated_as2_partners) == {
        ("ten_1", "platform_partner"),
        ("ten_2", "platform_partner"),
    }


@pytest.mark.asyncio
async def test_process_next_event_broadcasts_handles_permanent_errors(
    fake_tenant_port: FakeTenantPort,
    fake_replication_port: FakeReplicationPort,
) -> None:
    """If one tenant fails permanently during broadcast, it ignores it and continues."""
    fake_replication_port.permanent_fail_on_tenant = "ten_1"

    event = FakeOutboxEvent(
        id="evt_1",
        event_type=EdiEventType.edi_as2_partner_created.value,
        body={
            "tenant_id": PLATFORM_TENANT_ID,
            "event_type": EdiEventType.edi_as2_partner_created.value,
            "resource_id": "platform_partner",
            "idempotency_key": "ik_1",
        },
    )
    fake_outbox = FakeOutboxPort([event])
    service = ProvisioningWorkerService(fake_tenant_port, fake_outbox, fake_replication_port)

    processed = await service.process_next_event()
    assert processed is True

    # It skipped ten_1 (permanent error) but successfully replicated ten_2
    assert fake_replication_port.replicated_as2_partners == [("ten_2", "platform_partner")]


@pytest.mark.asyncio
async def test_process_next_event_broadcasts_bubbles_up_transient_errors(
    fake_tenant_port: FakeTenantPort,
    fake_replication_port: FakeReplicationPort,
) -> None:
    """If one tenant fails transiently during broadcast, it bubbles up to retry the whole batch."""
    fake_replication_port.transient_fail_on_tenant = "ten_1"

    event = FakeOutboxEvent(
        id="evt_1",
        event_type=EdiEventType.edi_as2_partner_created.value,
        body={
            "tenant_id": PLATFORM_TENANT_ID,
            "event_type": EdiEventType.edi_as2_partner_created.value,
            "resource_id": "platform_partner",
            "idempotency_key": "ik_1",
        },
    )
    fake_outbox = FakeOutboxPort([event])
    service = ProvisioningWorkerService(fake_tenant_port, fake_outbox, fake_replication_port)

    with pytest.raises(TransientProvisioningError):
        await service.process_next_event()


@pytest.mark.asyncio
async def test_process_next_event_invalid_payload() -> None:
    """An event that fails schema validation throws a PermanentProvisioningError (DLQ)."""
    event = FakeOutboxEvent(id="evt_1", event_type="random_garbage", body={"not_valid": True})
    fake_outbox = FakeOutboxPort([event])
    service = ProvisioningWorkerService(FakeTenantPort([]), fake_outbox, FakeReplicationPort())

    with pytest.raises(PermanentProvisioningError):
        await service.process_next_event()


@pytest.mark.asyncio
async def test_process_next_event_empty() -> None:
    """If the outbox is empty, it returns False safely."""
    fake_outbox = FakeOutboxPort([])
    service = ProvisioningWorkerService(FakeTenantPort([]), fake_outbox, FakeReplicationPort())

    processed = await service.process_next_event()
    assert processed is False
