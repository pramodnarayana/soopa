"""
Unit tests for the Outbound AS2 delivery path via DeliveryUseCase.

All test doubles imported from fakes.py (DRY).
NullAS2DeliveryAdapter is used to test the "AS2 not enabled" path.
"""

import pytest

from edi.adapters.outbound.pipeline.null_as2 import NullAS2DeliveryAdapter
from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.domain.events import PipelineEventType
from tests.pipeline.fakes import (
    FakeAS2DeliveryAdapter,
    FakeDataPlaneUnitOfWork,
    FakeHttpDeliveryAdapter,
    FakeSftpDeliveryAdapter,
    InMemoryRepositoryAdapter,
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


def make_use_case(
    uow: FakeDataPlaneUnitOfWork | None = None,
    as2: FakeAS2DeliveryAdapter | NullAS2DeliveryAdapter | None = None,
) -> DeliveryUseCase:
    u = uow or FakeDataPlaneUnitOfWork()
    a = as2 or FakeAS2DeliveryAdapter()
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
                "webhook_id": WebhookDeliveryStrategy(u_ref, FakeHttpDeliveryAdapter(), None),
                "sftp_partner_id": SftpDeliveryStrategy(u_ref, FakeSftpDeliveryAdapter(), None),
                "as2_partner_id": As2DeliveryStrategy(u_ref, a, None),
            },
        )

    return DeliveryUseCase(
        uow_factory=uow_factory,
        router_factory=router_factory,
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
    repo.local_as2_partners[str(_REMOTE_PARTNER["local_partner_id"])] = _LOCAL_PARTNER


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_deliver_as2_plain_no_crypto() -> None:
    """
    When no crypto material is configured, the raw EDI payload is transmitted
    as-is and the AS2 HTTP headers are correctly set.
    """
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    as2_adapter = FakeAS2DeliveryAdapter()

    trace_id = "trace-as2-plain"
    raw_edi = (
        b"ISA*00*          *00*          *ZZ*SENDER         "
        b"*ZZ*RECEIVER       *210101*1200*^*00501*000000001*0*P*>~"
    )
    _seed_as2_route(uow.repository, trace_id, raw_edi.decode("utf-8"))

    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow, as2=as2_adapter)
    await use_case.execute(trace_id)

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

    assert uow.repository.edi_messages[trace_id]["status"] == "DELIVERED"


async def test_deliver_as2_http_failure_sets_failed_status() -> None:
    """Non-2xx response from the trading partner must result in FAILED status."""
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    as2_adapter = FakeAS2DeliveryAdapter(status_code=503)

    trace_id = "trace-as2-fail"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "S1",
        "receiver_id": "R1",
        "trading_partner_id": "p-fail",
        "transaction_type": "856",
        "edi_data": "FAKE*EDI~",
        "status": "PENDING_DELIVERY",
    }
    uow.repository.routes.append(
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
    uow.repository.as2_partners["p-fail"] = remote
    uow.repository.local_as2_partners[str(_REMOTE_PARTNER["local_partner_id"])] = _LOCAL_PARTNER

    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow, as2=as2_adapter)
    await use_case.execute(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(uow.outbox.events) == 1
    outbox_event = uow.outbox.events[0]
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
    uow = FakeDataPlaneUnitOfWork()
    _seed_as2_route(uow.repository, "trace-as2-null", "EDI~", partner_id="p-null")

    # ── Act / Assert ───────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow, as2=NullAS2DeliveryAdapter())
    with pytest.raises(RuntimeError):
        await use_case.execute("trace-as2-null")

    assert len(uow.outbox.events) == 1
    outbox_event = uow.outbox.events[0]
    assert outbox_event["event_type"] == PipelineEventType.DELIVERY_COMPLETED
    assert outbox_event["payload"]["status"] == "FAILED"


async def test_deliver_as2_idempotent_claim() -> None:
    """
    A second delivery attempt on an already-PROCESSING message must be a no-op.
    The AS2 adapter must not be called.
    """
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    as2_adapter = FakeAS2DeliveryAdapter()

    trace_id = "trace-as2-idem"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "A",
        "receiver_id": "B",
        "trading_partner_id": "p-idem",
        "transaction_type": "810",
        "edi_data": "EDI~",
        "status": "PROCESSING",  # Already claimed — claim will return False
    }
    uow.repository.routes.append(
        {
            "route_id": "r-idem",
            "direction": "OUTBOUND",
            "isa_sender_id": "A",
            "isa_receiver_id": "B",
            "transaction_type": "*",
            "as2_partner_id": "p-idem",
        }
    )
    uow.repository.as2_partners["p-idem"] = {
        **_REMOTE_PARTNER,
        "remote_url": "https://idem.example.com/as2",
    }
    uow.repository.local_as2_partners[str(_REMOTE_PARTNER["local_partner_id"])] = _LOCAL_PARTNER

    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow, as2=as2_adapter)
    await use_case.execute(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(as2_adapter.delivered) == 0
    assert len(uow.outbox.events) == 0


async def test_deliver_as2_missing_local_partner_sets_failed() -> None:
    """
    If the AS2Partnership references a local_partner_id that doesn't exist,
    AS2MessageOrchestrator raises ValueError → delivery must be set to FAILED,
    not crash the worker process.
    """
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    as2_adapter = FakeAS2DeliveryAdapter()

    trace_id = "trace-as2-nolocal"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "X",
        "receiver_id": "Y",
        "trading_partner_id": "p-nolocal",
        "transaction_type": "850",
        "edi_data": "EDI~",
        "status": "PENDING_DELIVERY",
    }
    uow.repository.routes.append(
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
    uow.repository.as2_partners["p-nolocal"] = {
        **_REMOTE_PARTNER,
        "local_partner_id": "missing-local",
    }
    # Do NOT seed local_as2_partners["missing-local"]

    # ── Act ────────────────────────────────────────────────────────────────────
    use_case = make_use_case(uow=uow, as2=as2_adapter)
    with pytest.raises(RuntimeError):
        await use_case.execute(trace_id)

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(uow.outbox.events) == 1
    outbox_event = uow.outbox.events[0]
    assert outbox_event["event_type"] == PipelineEventType.DELIVERY_COMPLETED
    assert outbox_event["payload"]["status"] == "FAILED"
    assert len(as2_adapter.delivered) == 0
