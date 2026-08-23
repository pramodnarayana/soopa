"""
Unit tests for DeliveryUseCase — inbound webhook and outbound SFTP delivery paths.
All test doubles are imported from fakes.py (DRY). No mock library used.
"""

from typing import Any

import pytest

from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.domain.direction import MessageDirection
from edi.domain.status import MessageStatus
from tests.pipeline.fakes import (
    FakeAS2DeliveryAdapter,
    FakeDataPlaneUnitOfWork,
    FakeHttpDeliveryAdapter,
    FakeSftpDeliveryAdapter,
)

pytestmark = pytest.mark.asyncio


def make_use_case(
    uow: FakeDataPlaneUnitOfWork | None = None,
    sftp: FakeSftpDeliveryAdapter | None = None,
    http: FakeHttpDeliveryAdapter | None = None,
    vault: Any = None,
) -> DeliveryUseCase:
    u = uow or FakeDataPlaneUnitOfWork()
    s = sftp or FakeSftpDeliveryAdapter()
    h = http or FakeHttpDeliveryAdapter()
    a = FakeAS2DeliveryAdapter()
    import contextlib

    @contextlib.asynccontextmanager
    async def uow_factory():
        yield u

    def router_factory(u_ref):
        from edi.core.pipeline.delivery.as2 import As2DeliveryStrategy
        from edi.core.pipeline.delivery.router import DeliveryRouter
        from edi.core.pipeline.delivery.sftp import SftpDeliveryStrategy
        from edi.core.pipeline.delivery.webhook import WebhookDeliveryStrategy

        return DeliveryRouter(
            u_ref,
            {
                "webhook_id": WebhookDeliveryStrategy(u_ref, h, vault),
                "sftp_partner_id": SftpDeliveryStrategy(u_ref, s, vault),
                "as2_partner_id": As2DeliveryStrategy(u_ref, a, vault),
            },
        )

    return DeliveryUseCase(
        uow_factory=uow_factory,
        router_factory=router_factory,
    )


async def test_delivery_service_inbound_webhook() -> None:
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    http_adapter = FakeHttpDeliveryAdapter()

    trace_id = "trace-456"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": MessageDirection.INBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "edi_data": "FAKE*EDI*DATA~",
        "status": MessageStatus.PENDING_DELIVERY,
    }
    uow.repository.api_gateway[trace_id] = {
        "trace_id": trace_id,
        "payload": {"metadata": {"foo": "bar"}, "transactions": [{"hello": "world"}]},
        "status": MessageStatus.PENDING_DELIVERY,
    }
    uow.repository.routes.append(
        {
            "route_id": "r1",
            "direction": MessageDirection.INBOUND,
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "850",
            "webhook_id": "wp1",
        }
    )
    uow.repository.webhooks["wp1"] = {
        "name": "Test Webhook",
        "url": "https://webhook.example.com/edi",
        "auth_header_vault_ref": None,
    }

    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow, http=http_adapter)
    await use_case.execute(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(http_adapter.delivered) == 1
    assert http_adapter.delivered[0]["url"] == "https://webhook.example.com/edi"
    assert uow.repository.api_gateway[trace_id]["status"] == MessageStatus.DELIVERED


async def test_delivery_service_outbound_sftp() -> None:
    # ── Arrange ────────────────────────────────────────────────────────────────
    from tests.pipeline.fakes import FakeVault

    uow = FakeDataPlaneUnitOfWork()
    sftp_adapter = FakeSftpDeliveryAdapter()
    vault = FakeVault({"mock_password": "fake_private_key_data"})

    trace_id = "trace-sftp"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": MessageDirection.OUTBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "trading_partner_id": "sftp1",
        "transaction_type": "855",
        "edi_data": "FAKE*EDI*DATA~",
        "status": MessageStatus.PENDING_DELIVERY,
    }
    uow.repository.routes.append(
        {
            "route_id": "r2",
            "direction": MessageDirection.OUTBOUND,
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "*",
            "sftp_partner_id": "sftp1",
        }
    )
    uow.repository.sftp_partners["sftp1"] = {
        "host": "sftp.example.com",
        "port": 22,
        "username": "user",
        "credentials_vault_ref": "mock_password",
        "outbound_remote_path": "/out",
    }

    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow, sftp=sftp_adapter, vault=vault)
    await use_case.execute(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(sftp_adapter.delivered) == 1
    assert sftp_adapter.delivered[0]["client_key"] == "fake_private_key_data"
    assert sftp_adapter.delivered[0]["password"] == ""
    assert sftp_adapter.delivered[0]["host"] == "sftp.example.com"
    assert sftp_adapter.delivered[0]["payload"] == b"FAKE*EDI*DATA~"
    assert uow.repository.edi_messages[trace_id]["status"] == MessageStatus.DELIVERED


async def test_delivery_service_no_route_raises() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-err"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": MessageDirection.INBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "status": MessageStatus.PENDING_DELIVERY,
    }

    use_case = make_use_case(uow=uow)
    with pytest.raises(ValueError, match="No route found for"):
        await use_case.execute(trace_id)


async def test_delivery_service_http_failure_sets_failed_status() -> None:
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    http_adapter = FakeHttpDeliveryAdapter(status_code=503)

    trace_id = "trace-fail"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": MessageDirection.INBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "edi_data": "FAKE*EDI*DATA~",
        "status": MessageStatus.PENDING_DELIVERY,
    }
    uow.repository.api_gateway[trace_id] = {
        "trace_id": trace_id,
        "payload": {"metadata": {"foo": "bar"}, "transactions": [{"hello": "world"}]},
        "status": MessageStatus.PENDING_DELIVERY,
    }
    uow.repository.routes.append(
        {
            "route_id": "r1",
            "direction": MessageDirection.INBOUND,
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "850",
            "webhook_id": "wp1",
        }
    )
    uow.repository.webhooks["wp1"] = {
        "name": "Test",
        "url": "https://webhook.example.com/edi",
    }

    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow, http=http_adapter)
    await use_case.execute(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert uow.repository.api_gateway[trace_id]["status"] == MessageStatus.FAILED
    assert len(http_adapter.delivered) == 1
