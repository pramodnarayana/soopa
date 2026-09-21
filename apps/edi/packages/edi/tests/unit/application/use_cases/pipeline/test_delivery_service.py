import pytest

"""
Unit tests for DeliveryUseCase — inbound webhook and outbound SFTP delivery paths.
All test doubles are imported from fakes.py (DRY). No fake library used.
"""

import contextlib

from edi.application.use_cases.pipeline.delivery_router_use_case import (
    DeliveryRouterUseCase,
)
from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.domain.enums import EdiConnectionType, EdiDirection, MessageStatus
from edi.domain.exceptions import RouteNotFoundError
from edi.testing.fakes.pipeline_fakes import (
    FakeDataPlaneUnitOfWork,
    FakeHttpDeliveryAdapter,
    FakeSftpDeliveryAdapter,
    FakeVault,
)

pytestmark = pytest.mark.asyncio


def make_use_case(
    uow: FakeDataPlaneUnitOfWork | None = None,
) -> DeliveryUseCase:
    _u = uow or FakeDataPlaneUnitOfWork()

    @contextlib.asynccontextmanager
    async def uow_factory():
        yield _u

    def router_factory() -> DeliveryRouterUseCase:
        return DeliveryRouterUseCase(uow_factory)

    return DeliveryUseCase(
        uow_factory=uow_factory,
        router_factory=router_factory,
    )


async def test_delivery_service_inbound_webhook() -> None:
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    _http_adapter = FakeHttpDeliveryAdapter()

    trace_id = "trace-456"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": EdiDirection.INBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "edi_data": "FAKE*EDI*DATA~",
        "status": MessageStatus.PENDING_DELIVERY,
    }
    uow.api_gateway_transactions.api_gateway[trace_id] = {
        "trace_id": trace_id,
        "payload": {"metadata": {"foo": "bar"}, "transactions": [{"hello": "world"}]},
        "status": MessageStatus.PENDING_DELIVERY,
    }
    uow.repository.routes.append(
        {
            "tenant_id": "1",
            "route_id": "r1",
            "direction": EdiDirection.INBOUND,
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "850",
            "webhook_id": "wp1",
            "connection_type": EdiConnectionType.WEBHOOK,
        }
    )
    uow.repository.webhooks["wp1"] = {
        "id": "wp1",
        "name": "Test Webhook",
        "url": "https://webhook.example.com/edi",
        "active": True,
        "auth_header_vault_ref": None,
    }

    # ── Act ────────────────────────────────────────────────────────────────────
    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow)
    await use_case.execute(trace_id, idempotency_key="test-key")

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(uow.outbox.events) == 1
    event = uow.outbox.events[0]
    assert event["event_type"] == "EXECUTE_DELIVERY_COMMAND"
    assert event["payload"]["partner_id"] == "wp1"


async def test_delivery_service_outbound_sftp() -> None:
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    _sftp_adapter = FakeSftpDeliveryAdapter()
    _vault = FakeVault({"fake_password": "fake_private_key_data"})

    trace_id = "trace-sftp"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": EdiDirection.OUTBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "trading_partner_id": "sftp1",
        "transaction_type": "855",
        "edi_data": "FAKE*EDI*DATA~",
        "status": MessageStatus.PENDING_DELIVERY,
    }
    uow.repository.routes.append(
        {
            "tenant_id": "1",
            "route_id": "r2",
            "direction": EdiDirection.OUTBOUND,
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "*",
            "sftp_partner_id": "sftp1",
            "connection_type": EdiConnectionType.SFTP,
        }
    )
    uow.repository.sftp_partners["sftp1"] = {
        "id": "sftp1",
        "name": "sftp1",
        "host": "sftp.example.com",
        "port": 22,
        "username": "user",
        "inbound_remote_path": None,
        "outbound_remote_path": "/out",
        "host_key": None,
        "password": None,
        "credentials_vault_ref": "fake_password",
        "active": True,
    }

    # ── Act ────────────────────────────────────────────────────────────────────
    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow)
    await use_case.execute(trace_id, idempotency_key="test-key")

    # ── Assert ─────────────────────────────────────────────────────────────────
    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(uow.outbox.events) == 1
    event = uow.outbox.events[0]
    assert event["event_type"] == "EXECUTE_DELIVERY_COMMAND"
    assert event["payload"]["partner_id"] == "sftp1"


async def test_delivery_service_no_route_raises() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-err"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": EdiDirection.INBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "status": MessageStatus.PENDING_DELIVERY,
    }

    use_case = make_use_case(uow=uow)
    with pytest.raises(RouteNotFoundError, match="No route found for"):
        await use_case.execute(trace_id, idempotency_key="test-key")
