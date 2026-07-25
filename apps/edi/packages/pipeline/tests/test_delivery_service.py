"""
Unit tests for DeliveryService — inbound webhook and outbound SFTP paths.
All test doubles are imported from fakes.py (DRY). No mock library used.
"""

from typing import Any

import pytest
from domain.direction import MessageDirection
from domain.status import MessageStatus
from fakes import (
    FakeAS2DeliveryAdapter,
    FakeHttpDeliveryAdapter,
    FakeSftpDeliveryAdapter,
    InMemoryRepositoryAdapter,
    InMemoryStorageAdapter,
)

from pipeline.core.delivery import (
    As2DeliveryStrategy,
    DeliveryRouter,
    SftpDeliveryStrategy,
    WebhookDeliveryStrategy,
)

pytestmark = pytest.mark.asyncio


def make_service(
    repo: InMemoryRepositoryAdapter | None = None,
    sftp: FakeSftpDeliveryAdapter | None = None,
    http: FakeHttpDeliveryAdapter | None = None,
    vault: Any = None,
) -> DeliveryRouter:
    r = repo or InMemoryRepositoryAdapter()
    s = sftp or FakeSftpDeliveryAdapter()
    h = http or FakeHttpDeliveryAdapter()
    a = FakeAS2DeliveryAdapter()
    strategies = {
        "webhook_id": WebhookDeliveryStrategy(r, h, vault),
        "sftp_partner_id": SftpDeliveryStrategy(r, s, vault),
        "as2_partner_id": As2DeliveryStrategy(r, a, vault),
    }
    return DeliveryRouter(
        repository=r,
        strategies=strategies,
    )


async def test_delivery_service_inbound_webhook() -> None:
    # ── Arrange ────────────────────────────────────────────────────────────────
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    http_adapter = FakeHttpDeliveryAdapter()

    trace_id = "trace-456"
    s3_uri = "s3://fake-bucket/api_gateway/trace-456/transformed.json"
    edi_s3_uri = "s3://fake-bucket/edi_messages/trace-456/raw.edi"

    storage.store[s3_uri] = b'{"metadata": {"foo": "bar"}, "transactions": [{"hello": "world"}]}'

    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": MessageDirection.INBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "edi_data": edi_s3_uri,
        "status": MessageStatus.TRANSFORMED,
    }
    repo.api_gateway[trace_id] = {
        "trace_id": trace_id,
        "request": s3_uri,
        "payload": {"metadata": {"foo": "bar"}, "transactions": [{"hello": "world"}]},
        "status": MessageStatus.PENDING_DELIVERY,
    }
    repo.routes.append(
        {
            "route_id": "r1",
            "direction": MessageDirection.INBOUND,
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "850",
            "webhook_id": "wp1",
        }
    )
    repo.webhooks["wp1"] = {
        "name": "Test Webhook",
        "url": "https://webhook.example.com/edi",
        "auth_header_vault_ref": None,
    }

    # ── Act ────────────────────────────────────────────────────────────────────
    service = make_service(repo=repo, http=http_adapter)
    await service.deliver(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(http_adapter.delivered) == 1
    assert http_adapter.delivered[0]["url"] == "https://webhook.example.com/edi"
    assert repo.api_gateway[trace_id]["status"] == MessageStatus.DELIVERED


async def test_delivery_service_outbound_sftp() -> None:
    # ── Arrange ────────────────────────────────────────────────────────────────
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    sftp_adapter = FakeSftpDeliveryAdapter()

    trace_id = "trace-sftp"
    edi_s3_uri = "s3://fake-bucket/edi_messages/trace-sftp/transformed.edi"
    storage.store[edi_s3_uri] = b"FAKE*EDI*DATA~"

    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": MessageDirection.OUTBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "trading_partner_id": "sftp1",
        "transaction_type": "855",
        "edi_data": "FAKE*EDI*DATA~",
        "status": MessageStatus.PENDING_DELIVERY,
    }
    repo.routes.append(
        {
            "route_id": "r2",
            "direction": MessageDirection.OUTBOUND,
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "*",
            "sftp_partner_id": "sftp1",
        }
    )
    repo.sftp_partners["sftp1"] = {
        "host": "sftp.example.com",
        "port": 22,
        "username": "user",
        "credentials_vault_ref": "mock_password",
        "outbound_remote_path": "/out",
    }

    # ── Act ────────────────────────────────────────────────────────────────────
    from fakes import FakeVault

    vault = FakeVault({"mock_password": "fake_private_key_data"})

    service = make_service(repo=repo, sftp=sftp_adapter, vault=vault)
    await service.deliver(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(sftp_adapter.delivered) == 1
    assert sftp_adapter.delivered[0]["client_key"] == "fake_private_key_data"
    assert sftp_adapter.delivered[0]["password"] == ""
    assert sftp_adapter.delivered[0]["host"] == "sftp.example.com"
    assert sftp_adapter.delivered[0]["payload"] == b"FAKE*EDI*DATA~"
    assert repo.edi_messages[trace_id]["status"] == MessageStatus.DELIVERED


async def test_delivery_service_no_route_raises() -> None:
    repo = InMemoryRepositoryAdapter()
    trace_id = "trace-err"
    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": MessageDirection.INBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
    }

    service = make_service(repo=repo)
    with pytest.raises(ValueError, match="No route found"):
        await service.deliver(trace_id)


async def test_delivery_service_http_failure_sets_failed_status() -> None:
    # ── Arrange ────────────────────────────────────────────────────────────────
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    http_adapter = FakeHttpDeliveryAdapter(status_code=503)

    trace_id = "trace-fail"
    s3_uri = "s3://fake-bucket/api_gateway/trace-fail/transformed.json"
    storage.store[s3_uri] = b'{"metadata": {"foo": "bar"}, "transactions": [{"hello": "world"}]}'

    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": MessageDirection.INBOUND,
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "status": MessageStatus.TRANSFORMED,
    }
    repo.api_gateway[trace_id] = {
        "trace_id": trace_id,
        "request": s3_uri,
        "payload": {"metadata": {"foo": "bar"}, "transactions": [{"hello": "world"}]},
        "status": MessageStatus.PENDING_DELIVERY,
    }
    repo.routes.append(
        {
            "route_id": "r1",
            "direction": MessageDirection.INBOUND,
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "850",
            "webhook_id": "wp1",
        }
    )
    repo.webhooks["wp1"] = {
        "name": "Test",
        "url": "https://webhook.example.com/edi",
    }

    # ── Act ────────────────────────────────────────────────────────────────────
    service = make_service(repo=repo, http=http_adapter)
    await service.deliver(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert repo.api_gateway[trace_id]["status"] == MessageStatus.FAILED
    assert len(http_adapter.delivered) == 1
