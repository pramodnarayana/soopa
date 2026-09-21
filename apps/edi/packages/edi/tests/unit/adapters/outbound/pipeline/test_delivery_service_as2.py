"""
Unit tests for the Outbound AS2 delivery path via As2DeliveryStrategy.

All test doubles imported from fakes.py (DRY).
NullAS2DeliveryAdapter is used to test the "AS2 not enabled" path.
"""

import contextlib
import copy

import pytest

from edi.adapters.outbound.pipeline.null_as2 import NullAS2DeliveryAdapter
from edi.application.use_cases.pipeline.delivery_router_use_case import (
    DeliveryRouterUseCase,
)
from edi.application.use_cases.pipeline.delivery_use_case import DeliveryUseCase
from edi.core.pipeline.delivery.as2 import As2DeliveryStrategy
from edi.core.pipeline.delivery.base import TerminalDeliveryError
from edi.domain.enums import PipelineEventType
from edi.testing.fakes.pipeline_fakes import (
    FakeAS2DeliveryAdapter,
    FakeDataPlaneUnitOfWork,
    InMemoryRepositoryAdapter,
)

pytestmark = pytest.mark.asyncio

# ── AS2 partner fixture data ──────────────────────────────────────────────────

_REMOTE_PARTNER = {
    "remote": {
        "id": "remote-1",
        "name": "Walmart AS2",
        "as2_id": "WALMART",
        "url": "https://as2.walmart.com/receive",
        "public_cert_pem": None,
        "public_cert_vault_ref": None,
        "prev_public_cert_pem": None,
        "prev_public_cert_vault_ref": None,
    },
    "partnership": {
        "id": "partnership-1",
        "name": "Walmart Partnership",
        "local_partner_id": "local-p1",
        "remote_partner_id": "remote-1",
        "active": True,
        "credentials_vault_ref": None,
        "encryption_algorithm": "AES256",
        "signature_algorithm": "SHA256",
        "mdn_type": "SYNC",
        "mdn_url": None,
        "advanced_flags": None,
    },
}

_LOCAL_PARTNER = {
    "id": "local-p1",
    "name": "Acme AS2",
    "as2_id": "ACME",
    "private_key_vault_ref": None,
    "public_cert_pem": None,
}


def make_use_case(
    uow: FakeDataPlaneUnitOfWork | None = None,
) -> DeliveryUseCase:
    u = uow or FakeDataPlaneUnitOfWork()

    @contextlib.asynccontextmanager
    async def uow_factory():
        yield u

    def router_factory() -> DeliveryRouterUseCase:
        return DeliveryRouterUseCase(uow_factory)

    return DeliveryUseCase(
        router_factory=router_factory,
    )


def make_as2_strategy(
    uow: FakeDataPlaneUnitOfWork,
    as2: FakeAS2DeliveryAdapter | NullAS2DeliveryAdapter,
) -> As2DeliveryStrategy:
    @contextlib.asynccontextmanager
    async def uow_factory():
        yield uow

    return As2DeliveryStrategy(uow_factory, as2)


def _seed_as2_route(
    repo: InMemoryRepositoryAdapter, trace_id: str, payload: str, partner_id: str = "remote-1"
) -> None:
    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "SENDER",
        "receiver_id": "RECEIVER",
        "trading_partner_id": partner_id,
        "transaction_type": "850",
        "edi_data": payload,
        "status": "PENDING_DELIVERY",
    }
    repo.routes.append(
        {
            "tenant_id": "1",
            "route_id": f"r-{trace_id}",
            "direction": "OUTBOUND",
            "isa_sender_id": "SENDER",
            "isa_receiver_id": "RECEIVER",
            "transaction_type": "*",
            "as2_partner_id": partner_id,
            "connection_type": "AS2",
        }
    )
    partner_copy = dict(_REMOTE_PARTNER)
    partner_copy["remote"] = dict(partner_copy["remote"])
    partner_copy["remote"]["id"] = partner_id
    partner_copy["partnership"] = dict(partner_copy["partnership"])
    partner_copy["partnership"]["remote_partner_id"] = partner_id

    repo.as2_partners[partner_id] = partner_copy
    repo.as2_partners[str(partner_copy["partnership"]["local_partner_id"])] = _LOCAL_PARTNER


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_delivery_router_emits_execute_delivery_command() -> None:
    """
    DeliveryRouterUseCase should emit an EXECUTE_DELIVERY_COMMAND outbox event.
    """
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-router"
    _seed_as2_route(uow.repository, trace_id, "EDI")

    use_case = make_use_case(uow=uow)
    await use_case.execute(trace_id, idempotency_key="test-key")

    assert len(uow.outbox.events) == 1
    event = uow.outbox.events[0]
    assert event["event_type"] == PipelineEventType.EXECUTE_DELIVERY_COMMAND.value
    assert event["payload"]["strategy_type"] == "as2_partner_id"
    assert event["payload"]["partner_id"] == "remote-1"
    assert event["payload"]["trace_id"] == trace_id


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
    strategy = make_as2_strategy(uow, as2_adapter)
    edi_msg = await uow.repository.get_edi_message(trace_id)
    await strategy.deliver(trace_id, "remote-1", edi_msg, "fixed-idem-key")

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


async def test_deliver_as2_http_failure_bubbles_as_transient() -> None:
    """Non-2xx response from the trading partner must bubble as transient error."""
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
            "tenant_id": "1",
            "route_id": "r-fail",
            "direction": "OUTBOUND",
            "isa_sender_id": "S1",
            "isa_receiver_id": "R1",
            "transaction_type": "*",
            "as2_partner_id": "p-fail",
            "connection_type": "AS2",
        }
    )
    remote = copy.deepcopy(_REMOTE_PARTNER)
    remote["remote"]["url"] = "https://fail.example.com/as2"
    remote["remote"]["id"] = "p-fail"
    remote["partnership"]["remote_partner_id"] = "p-fail"
    uow.repository.as2_partners["p-fail"] = remote
    uow.repository.as2_partners[str(_REMOTE_PARTNER["partnership"]["local_partner_id"])] = (
        _LOCAL_PARTNER
    )

    # ── Act ────────────────────────────────────────────────────────────────────
    strategy = make_as2_strategy(uow, as2_adapter)
    edi_msg = await uow.repository.get_edi_message(trace_id)
    with pytest.raises(RuntimeError):
        await strategy.deliver(trace_id, "p-fail", edi_msg, "fixed-idem-key")

    with pytest.raises(RuntimeError):
        await strategy.deliver(trace_id, "p-fail", edi_msg, "fixed-idem-key")

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(uow.outbox.events) == 0
    assert uow.repository.edi_messages[trace_id]["status"] == "PENDING_DELIVERY"
    assert len(as2_adapter.delivered) == 2

    # Verify identical Message-IDs are used across retries
    headers_1 = as2_adapter.delivered[0]["headers"]
    headers_2 = as2_adapter.delivered[1]["headers"]
    assert headers_1["Message-ID"] == headers_2["Message-ID"]


async def test_deliver_as2_failed_mdn_emits_one_failure_event() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-as2-failed-mdn"
    _seed_as2_route(uow.repository, trace_id, "FAKE*EDI~")
    failed_mdn = (
        b"------=_MDNBoundary\r\n"
        b"Content-Type: text/plain; charset=us-ascii\r\n\r\n"
        b"The AS2 message failed.\r\n"
        b"------=_MDNBoundary\r\n"
        b"Content-Type: message/disposition-notification\r\n\r\n"
        b"Original-Message-ID: <msg-123>\r\n"
        b"Disposition: automatic-action/MDN-sent-automatically; failed/error\r\n"
        b"------=_MDNBoundary--\r\n"
    )
    as2_adapter = FakeAS2DeliveryAdapter(body=failed_mdn)

    strategy = make_as2_strategy(uow, as2_adapter)
    edi_msg = await uow.repository.get_edi_message(trace_id)
    with pytest.raises(TerminalDeliveryError, match="Sync MDN indicates failure"):
        await strategy.deliver(trace_id, "remote-1", edi_msg, "fixed-idem-key")


async def test_deliver_as2_null_adapter_is_caught_and_bubbles_transient() -> None:
    """
    NullAS2DeliveryAdapter raises RuntimeError, which is bubbled up as a transient error
    so it can be retried (or moved to DLQ) rather than marked FAILED in the domain.
    """
    # ── Arrange ────────────────────────────────────────────────────────────────
    uow = FakeDataPlaneUnitOfWork()
    _seed_as2_route(uow.repository, "trace-as2-null", "EDI~", partner_id="p-null")

    # ── Act / Assert ───────────────────────────────────────────────────────────
    strategy = make_as2_strategy(uow, NullAS2DeliveryAdapter())
    edi_msg = await uow.repository.get_edi_message("trace-as2-null")
    with pytest.raises(RuntimeError):
        await strategy.deliver("trace-as2-null", "p-null", edi_msg, "fixed-idem-key")

    assert len(uow.outbox.events) == 0
    assert uow.repository.edi_messages["trace-as2-null"]["status"] == "PENDING_DELIVERY"


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
            "tenant_id": "1",
            "route_id": "r-nolocal",
            "direction": "OUTBOUND",
            "isa_sender_id": "X",
            "isa_receiver_id": "Y",
            "transaction_type": "*",
            "as2_partner_id": "p-nolocal",
            "connection_type": "AS2",
        }
    )
    # local_partner_id points to a partner that does NOT exist in local_as2_partners
    nolocal_remote = copy.deepcopy(_REMOTE_PARTNER)
    nolocal_remote["partnership"]["local_partner_id"] = "missing-local"
    nolocal_remote["partnership"]["remote_partner_id"] = "p-nolocal"
    uow.repository.as2_partners["p-nolocal"] = nolocal_remote
    # Do NOT seed local_as2_partners["missing-local"]

    # ── Act ────────────────────────────────────────────────────────────────────
    strategy = make_as2_strategy(uow, as2_adapter)
    edi_msg = await uow.repository.get_edi_message(trace_id)
    with pytest.raises(TerminalDeliveryError, match="Local AS2 partner config is missing"):
        await strategy.deliver(trace_id, "p-nolocal", edi_msg, "fixed-idem-key")

    # ── Assert ─────────────────────────────────────────────────────────────────
    assert len(as2_adapter.delivered) == 0
