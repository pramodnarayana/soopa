"""
Unit tests for the Outbound AS2 delivery path in DeliveryService.

All test doubles imported from fakes.py (DRY).
NullAS2DeliveryAdapter is used to test the "AS2 not enabled" path —
replacing the previous `as2_delivery=None` anti-pattern.
"""

import pytest
from domain.events import PipelineEventType
from fakes import (
    FakeAS2DeliveryAdapter,
    FakeHttpDeliveryAdapter,
    FakeSftpDeliveryAdapter,
    InMemoryRepositoryAdapter,
    InMemoryStorageAdapter,
)

from pipeline.adapters.null_as2 import NullAS2DeliveryAdapter
from pipeline.core.delivery import (
    As2DeliveryStrategy,
    DeliveryRouter,
    SftpDeliveryStrategy,
    WebhookDeliveryStrategy,
)

pytestmark = pytest.mark.asyncio

# ── AS2 partner fixture data ──────────────────────────────────────────────────

_REMOTE_PARTNER = {
    "name": "Walmart AS2",
    "as2_id": "WALMART",
    "remote_url": "https://as2.walmart.com/receive",
    "local_partner_id": "local-p1",
    "public_cert_pem": None,
    "public_cert_vault_ref": None,
    "encryption_algorithm": "AES256",
    "signature_algorithm": "SHA256",
    "mdn_type": "SYNC",
    "mdn_url": None,
}

_LOCAL_PARTNER = {
    "name": "Our AS2 Gateway",
    "as2_id": "ACME",
    "public_cert_pem": None,
    "public_cert_vault_ref": None,
    "private_key_vault_ref": None,
}


def make_service(
    repo: InMemoryRepositoryAdapter | None = None,
    as2: FakeAS2DeliveryAdapter | NullAS2DeliveryAdapter | None = None,
) -> DeliveryRouter:
    r = repo or InMemoryRepositoryAdapter()
    a = as2 or FakeAS2DeliveryAdapter()
    h = FakeHttpDeliveryAdapter()
    s = FakeSftpDeliveryAdapter()
    strategies = {
        "webhook_id": WebhookDeliveryStrategy(r, h, None),
        "sftp_partner_id": SftpDeliveryStrategy(r, s, None),
        "as2_partner_id": As2DeliveryStrategy(r, a, None),
    }
    return DeliveryRouter(
        repository=r,
        strategies=strategies,
    )


def _seed_as2_route(
    repo: InMemoryRepositoryAdapter,
    trace_id: str,
    edi_data: str,
    partner_id: str = "remote-p1",
    transaction_type: str = "850",
) -> None:
    """Seeds all repository state needed for an outbound AS2 delivery."""
    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "SENDER",
        "receiver_id": "RECEIVER",
        "trading_partner_id": partner_id,
        "transaction_type": transaction_type,
        "edi_data": edi_data,
        "status": "PENDING_DELIVERY",
    }
    repo.routes.append(
        {
            "route_id": f"r-{trace_id}",
            "direction": "OUTBOUND",
            "isa_sender_id": "SENDER",
            "isa_receiver_id": "RECEIVER",
            "transaction_type": "*",
            "as2_partner_id": partner_id,
        }
    )
    repo.as2_partners[partner_id] = _REMOTE_PARTNER
    repo.local_as2_partners[_REMOTE_PARTNER["local_partner_id"]] = _LOCAL_PARTNER


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_deliver_as2_plain_no_crypto() -> None:
    """
    When no crypto material is configured, the raw EDI payload is transmitted
    as-is and the AS2 HTTP headers are correctly set.
    """
    # ── Arrange ────────────────────────────────────────────────────────────────
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    as2_adapter = FakeAS2DeliveryAdapter()

    trace_id = "trace-as2-plain"
    edi_s3_uri = f"s3://bucket/edi/{trace_id}/raw.edi"
    raw_edi = (
        b"ISA*00*          *00*          *ZZ*SENDER         "
        b"*ZZ*RECEIVER       *210101*1200*^*00501*000000001*0*P*>~"
    )
    storage.store[edi_s3_uri] = raw_edi
    _seed_as2_route(repo, trace_id, raw_edi.decode("utf-8"))

    # ── Act ────────────────────────────────────────────────────────────────────
    await make_service(repo=repo, as2=as2_adapter).deliver(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(as2_adapter.delivered) == 1
    call = as2_adapter.delivered[0]

    assert call["url"] == "https://as2.walmart.com/receive"
    assert call["body"] == raw_edi

    headers = call["headers"]
    assert headers["AS2-From"] == "ACME"
    assert headers["AS2-To"] == "WALMART"
    assert "Message-ID" in headers
    assert "Disposition-Notification-To" in headers

    assert repo.edi_messages[trace_id]["status"] == "DELIVERED"


async def test_deliver_as2_http_failure_sets_failed_status() -> None:
    """Non-2xx response from the trading partner must result in FAILED status."""
    # ── Arrange ────────────────────────────────────────────────────────────────
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    as2_adapter = FakeAS2DeliveryAdapter(status_code=503)

    trace_id = "trace-as2-fail"
    edi_s3_uri = f"s3://bucket/edi/{trace_id}/raw.edi"
    storage.store[edi_s3_uri] = b"FAKE*EDI~"

    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "S1",
        "receiver_id": "R1",
        "trading_partner_id": "p-fail",
        "transaction_type": "856",
        "edi_data": "FAKE*EDI~",
        "status": "PENDING_DELIVERY",
    }
    repo.routes.append(
        {
            "route_id": "r-fail",
            "direction": "OUTBOUND",
            "isa_sender_id": "S1",
            "isa_receiver_id": "R1",
            "transaction_type": "*",
            "as2_partner_id": "p-fail",
        }
    )
    remote = {**_REMOTE_PARTNER, "remote_url": "https://fail.example.com/as2"}
    repo.as2_partners["p-fail"] = remote
    repo.local_as2_partners[_REMOTE_PARTNER["local_partner_id"]] = _LOCAL_PARTNER

    # ── Act ────────────────────────────────────────────────────────────────────
    await make_service(repo=repo, as2=as2_adapter).deliver(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(repo.outbox) == 1
    outbox_event = repo.outbox[0]
    assert outbox_event["event_type"] == PipelineEventType.DELIVERY_COMPLETED
    assert outbox_event["payload"]["status"] == "FAILED"
    assert len(as2_adapter.delivered) == 1


async def test_deliver_as2_null_adapter_is_caught_and_marked_failed() -> None:
    """
    NullAS2DeliveryAdapter replaces the previous `as2_delivery=None` anti-pattern.
    When AS2 is routed but the Null adapter is injected, it raises a RuntimeError
    which is caught internally and the message is marked as FAILED.
    """
    # ── Arrange ────────────────────────────────────────────────────────────────
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()

    trace_id = "trace-as2-null"
    edi_s3_uri = f"s3://bucket/edi/{trace_id}/raw.edi"
    storage.store[edi_s3_uri] = b"EDI~"
    _seed_as2_route(repo, trace_id, "EDI~", partner_id="p-null")

    # ── Act / Assert ───────────────────────────────────────────────────────────
    service = make_service(repo=repo, as2=NullAS2DeliveryAdapter())
    # It should catch the RuntimeError and mark the message as FAILED, but bubble up the error
    import pytest

    with pytest.raises(RuntimeError):
        await service.deliver(trace_id)

    assert len(repo.outbox) == 1
    outbox_event = repo.outbox[0]
    assert outbox_event["event_type"] == PipelineEventType.DELIVERY_COMPLETED
    assert outbox_event["payload"]["status"] == "FAILED"


async def test_deliver_as2_idempotent_claim() -> None:
    """
    A second delivery attempt on an already-PROCESSING message must be a no-op.
    The AS2 adapter must not be called.
    """
    # ── Arrange ────────────────────────────────────────────────────────────────
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    as2_adapter = FakeAS2DeliveryAdapter()

    trace_id = "trace-as2-idem"
    edi_s3_uri = f"s3://bucket/edi/{trace_id}/raw.edi"
    storage.store[edi_s3_uri] = b"EDI~"

    # Already PROCESSING — claim_edi_message returns False
    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "A",
        "receiver_id": "B",
        "trading_partner_id": "p-idem",
        "transaction_type": "810",
        "edi_data": "EDI~",
        "status": "PROCESSING",
    }
    repo.routes.append(
        {
            "route_id": "r-idem",
            "direction": "OUTBOUND",
            "isa_sender_id": "A",
            "isa_receiver_id": "B",
            "transaction_type": "*",
            "as2_partner_id": "p-idem",
        }
    )
    repo.as2_partners["p-idem"] = {**_REMOTE_PARTNER, "remote_url": "https://idem.example.com/as2"}
    repo.local_as2_partners[_REMOTE_PARTNER["local_partner_id"]] = _LOCAL_PARTNER

    # ── Act ────────────────────────────────────────────────────────────────────
    await make_service(repo=repo, as2=as2_adapter).deliver(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(as2_adapter.delivered) == 0
    assert len(repo.outbox) == 0


async def test_deliver_as2_missing_local_partner_sets_failed() -> None:
    """
    If the AS2Partnership references a local_partner_id that doesn't exist,
    AS2MessageOrchestrator raises ValueError → delivery must be set to FAILED,
    not crash the worker process.
    """
    # ── Arrange ────────────────────────────────────────────────────────────────
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    as2_adapter = FakeAS2DeliveryAdapter()

    trace_id = "trace-as2-nolocal"
    edi_s3_uri = f"s3://bucket/edi/{trace_id}/raw.edi"
    storage.store[edi_s3_uri] = b"EDI~"

    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "X",
        "receiver_id": "Y",
        "trading_partner_id": "p-nolocal",
        "transaction_type": "850",
        "edi_data": "EDI~",
        "status": "PENDING_DELIVERY",
    }
    repo.routes.append(
        {
            "route_id": "r-nolocal",
            "direction": "OUTBOUND",
            "isa_sender_id": "X",
            "isa_receiver_id": "Y",
            "transaction_type": "*",
            "as2_partner_id": "p-nolocal",
        }
    )
    # local_partner_id points to a partner that does NOT exist in local_as2_partners
    repo.as2_partners["p-nolocal"] = {**_REMOTE_PARTNER, "local_partner_id": "missing-local"}
    # Do NOT seed local_as2_partners["missing-local"]

    # ── Act ────────────────────────────────────────────────────────────────────
    import pytest

    with pytest.raises(RuntimeError):
        await make_service(repo=repo, as2=as2_adapter).deliver(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(repo.outbox) == 1
    outbox_event = repo.outbox[0]
    assert outbox_event["event_type"] == PipelineEventType.DELIVERY_COMPLETED
    assert outbox_event["payload"]["status"] == "FAILED"
    assert len(as2_adapter.delivered) == 0
