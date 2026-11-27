"""Unit tests for first-class ISA routing, inactive-route persistence, and secret retrieval errors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from identity.domain.identity_context import PLATFORM_TENANT_ID
from secret_store.testing.fakes.in_memory_vault import InMemoryVaultAdapter

from edi.adapters.outbound.security.smime_crypto_service import SmimeCryptoService
from edi.application.use_cases.process_inbound_as2_message_use_case import (
    InboundAs2DataPlaneUoWPort,
    ProcessInboundAs2Command,
    ProcessInboundAs2MessageUseCase,
)
from edi.domain.exceptions import EdiErrorCode, OrchestrationError, RouteNotActiveEdiError
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.domain.routing.inbound_route import InboundRoute
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus
from edi.testing.fakes.api_fakes import FakeControlPlaneUnitOfWork

_SAMPLE_X12_PAYLOAD = (
    b"ISA*00*          *00*          *ZZ*LOGIFLOW       *ZZ*GLTP           "
    b"*261126*1526*U*00401*000000001*0*T*>~"
    b"GS*PO*LOGIFLOW*GLTP*20261126*1526*1*X*004010~"
    b"ST*850*0001~SE*2*0001~GE*1*1~IEA*1*000000001~"
)


class _RecordingEdiMessageRepo:
    def __init__(self) -> None:
        self.saved: list[EdiMessage] = []

    async def save(self, aggregate: EdiMessage) -> None:
        self.saved.append(aggregate)


class _RecordingDataPlaneUoW:
    def __init__(self) -> None:
        self.edi_messages = _RecordingEdiMessageRepo()
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _RecordingDataPlaneFactory:
    def __init__(self) -> None:
        self.requested_tenants: list[str] = []
        self.uow = _RecordingDataPlaneUoW()

    @asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, app_slug: str = "edi"
    ) -> AsyncIterator[InboundAs2DataPlaneUoWPort]:
        self.requested_tenants.append(tenant_id)
        yield self.uow


def _seed_partnership(
    cp_uow: FakeControlPlaneUnitOfWork,
    *,
    local_private_key_ref: str | None = None,
) -> None:
    now = datetime.now(UTC)
    local_partner = AS2Partner(
        id="edi_as2_tp_local",
        tenant_id=PLATFORM_TENANT_ID,
        name="Flowwolf Local",
        as2_id="FLOWWOLF_LOCAL_AS2",
        is_local=True,
        active=True,
        private_key_vault_ref=local_private_key_ref,
        created_at=now,
        updated_at=now,
    )
    remote_partner = AS2Partner(
        id="edi_as2_tp_remote",
        tenant_id=PLATFORM_TENANT_ID,
        name="Open AS2",
        as2_id="OPEN_AS2",
        is_local=False,
        active=True,
        created_at=now,
        updated_at=now,
    )
    partnership = AS2Partnership(
        id="edi_as2_pship_1",
        tenant_id=PLATFORM_TENANT_ID,
        name="Flowwolf Local - OpenAS2",
        local_partner_id=local_partner.id,
        remote_partner_id=remote_partner.id,
        mdn_type="sync",
        encryption_algorithm="aes256",
        signature_algorithm="sha256",
        active=True,
        created_at=now,
        updated_at=now,
    )
    cp_uow.as2_partners.partners[local_partner.id] = local_partner
    cp_uow.as2_partners.partners[remote_partner.id] = remote_partner
    cp_uow.as2_partnerships.partnerships[partnership.id] = partnership


def _sample_command() -> ProcessInboundAs2Command:
    return ProcessInboundAs2Command(
        headers={
            "as2-from": "OPEN_AS2",
            "as2-to": "FLOWWOLF_LOCAL_AS2",
            "message-id": "<msg-isa-test@openas2>",
            "content-type": "application/edi-x12",
        },
        body_bytes=_SAMPLE_X12_PAYLOAD,
    )


@pytest.mark.asyncio
async def test_inactive_inbound_route_saves_received_message_and_returns_processed_mdn() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    _seed_partnership(cp_uow)
    now = datetime.now(UTC)
    cp_uow.inbound_routes.inbound_routes["edi_inb_rt_inactive"] = InboundRoute(
        id="edi_inb_rt_inactive",
        tenant_id="iam_ten_customer_1",
        name="Logiflow To Greatlakes",
        isa_sender_id="LOGIFLOW",
        isa_receiver_id="GLTP",
        transaction_type="850",
        active=False,
        created_at=now,
        updated_at=now,
    )

    dp_factory = _RecordingDataPlaneFactory()
    use_case = ProcessInboundAs2MessageUseCase(
        control_plane_uow=cp_uow,
        dp_factory=dp_factory,
        secret_store=InMemoryVaultAdapter(),
        crypto_service=SmimeCryptoService(),
    )

    result = await use_case.process_inbound_message(_sample_command())
    assert result.is_ok
    processed = result.unwrap()

    # Remote TP receives a valid RFC 4130 processed MDN (NOT an error MDN)
    assert b"processed" in processed.mdn_body
    assert b"error:" not in processed.mdn_body

    # First-class RouteNotActiveEdiError attached with ISA pair and route details
    assert isinstance(processed.routing_error, RouteNotActiveEdiError)
    assert processed.routing_error.code == EdiErrorCode.ROUTE_NOT_ACTIVE
    assert "Route Not Active" in processed.routing_error.message
    assert "LOGIFLOW" in processed.routing_error.message
    assert "GLTP" in processed.routing_error.message
    assert "Logiflow To Greatlakes" in processed.routing_error.message

    # Payload durably persisted in the owning tenant's shard with full metadata and status=RECEIVED
    assert dp_factory.requested_tenants == ["iam_ten_customer_1"]
    assert dp_factory.uow.committed is True
    assert len(dp_factory.uow.edi_messages.saved) == 1

    saved_msg = dp_factory.uow.edi_messages.saved[0]
    assert saved_msg.status == MessageStatus.RECEIVED
    assert saved_msg.transaction_type == "850"
    assert saved_msg.interchange_control_no == "000000001"
    assert saved_msg.file_size_bytes == len(_SAMPLE_X12_PAYLOAD)
    assert saved_msg.error_code == EdiErrorCode.ROUTE_NOT_ACTIVE.value
    assert saved_msg.status_message is not None
    assert "Route Not Active" in saved_msg.status_message
    assert "LOGIFLOW" in saved_msg.status_message
    assert "GLTP" in saved_msg.status_message
    assert saved_msg.edi_data == _SAMPLE_X12_PAYLOAD.decode("utf-8")
    # Held before transform until route is activated and replayed
    assert saved_msg.domain_events == []
    assert len(saved_msg.trace_events) == 1
    trace_meta = saved_msg.trace_events[0].metadata
    assert trace_meta is not None
    assert trace_meta["error_code"] == EdiErrorCode.ROUTE_NOT_ACTIVE.value


@pytest.mark.asyncio
async def test_missing_inbound_route_returns_first_class_error_with_isa_pair() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    _seed_partnership(cp_uow)
    dp_factory = _RecordingDataPlaneFactory()

    use_case = ProcessInboundAs2MessageUseCase(
        control_plane_uow=cp_uow,
        dp_factory=dp_factory,
        secret_store=InMemoryVaultAdapter(),
        crypto_service=SmimeCryptoService(),
    )

    result = await use_case.process_inbound_message(_sample_command())
    assert result.is_err
    err = result.unwrap_err()
    assert err.code == EdiErrorCode.AS2_TENANT_NOT_FOUND
    assert "LOGIFLOW" in err.message
    assert "GLTP" in err.message
    assert err.details["isa_sender"] == "LOGIFLOW"
    assert err.details["isa_receiver"] == "GLTP"
    assert dp_factory.requested_tenants == []


@pytest.mark.asyncio
@pytest.mark.parametrize("route_active", [True, False])
async def test_ambiguous_multi_tenant_isa_pair_never_leaks_to_any_shard(
    route_active: bool,
) -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    _seed_partnership(cp_uow)
    now = datetime.now(UTC)
    for idx in (1, 2):
        cp_uow.inbound_routes.inbound_routes[f"edi_inb_rt_{idx}"] = InboundRoute(
            id=f"edi_inb_rt_{idx}",
            tenant_id=f"iam_ten_customer_{idx}",
            name=f"Route {idx}",
            isa_sender_id="LOGIFLOW",
            isa_receiver_id="GLTP",
            transaction_type="850",
            active=route_active,
            created_at=now,
            updated_at=now,
        )

    dp_factory = _RecordingDataPlaneFactory()
    use_case = ProcessInboundAs2MessageUseCase(
        control_plane_uow=cp_uow,
        dp_factory=dp_factory,
        secret_store=InMemoryVaultAdapter(),
        crypto_service=SmimeCryptoService(),
    )

    result = await use_case.process_inbound_message(_sample_command())
    assert result.is_err
    err = result.unwrap_err()
    assert err.code == EdiErrorCode.AS2_AMBIGUOUS_ISA_ROUTE
    assert "LOGIFLOW" in err.message
    assert "GLTP" in err.message
    assert err.details["matched_tenant_ids"] == ["iam_ten_customer_1", "iam_ten_customer_2"]
    assert dp_factory.requested_tenants == []


@pytest.mark.asyncio
async def test_missing_secret_in_vault_raises_orchestration_error_not_raw_value_error() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    _seed_partnership(cp_uow, local_private_key_ref="as2_key/missing_key_ref")
    dp_factory = _RecordingDataPlaneFactory()

    use_case = ProcessInboundAs2MessageUseCase(
        control_plane_uow=cp_uow,
        dp_factory=dp_factory,
        secret_store=InMemoryVaultAdapter(),
        crypto_service=SmimeCryptoService(),
    )

    with pytest.raises(OrchestrationError, match="local_private_key"):
        await use_case.process_inbound_message(_sample_command())
