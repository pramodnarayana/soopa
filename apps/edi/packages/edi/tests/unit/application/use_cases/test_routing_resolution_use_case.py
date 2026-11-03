"""
Unit tests for RoutingResolutionUseCase against single-aggregate repositories.

Covers:
- Outbound replay race window (EdiMessage absent while EdiJson is committed)
- Outbound resolution via OutboundRoute -> AS2Partner / SFTPPartner and business_metadata fallback
- Inbound resolution via AS2 sender ID and InboundRoute -> SFTPPartner / Webhook
- ResolvedRoutingContextDTO.enrich_message connection_type hydration
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.domain.types import JsonDict

from edi.application.responses import EdiJsonDTO, EdiMessageDTO
from edi.application.use_cases.routing_resolution_use_case import (
    ResolvedRoutingContextDTO,
    ResolveRoutingContextQuery,
    RoutingResolutionUseCase,
)
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.sftp.partner import SFTPPartner
from edi.domain.routing.enums import ConnectionType
from edi.domain.routing.inbound_route import InboundRoute
from edi.domain.routing.outbound_route import OutboundRoute
from edi.domain.routing.webhook import Webhook
from edi.testing.fakes.api_fakes import FakeControlPlaneUnitOfWork

TENANT_ID = "tenant-001"


def _make_edi_json(
    trace_id: str = "trace-001",
    direction: str = "OUTBOUND",
    trading_partner_id: str | None = "tp-001",
    transaction_type: str | None = "850",
    business_metadata: JsonDict | None = None,
) -> EdiJsonDTO:
    now = datetime.now(UTC)
    return EdiJsonDTO(
        id="json-001",
        trace_id=trace_id,
        direction=direction,
        trading_partner_id=trading_partner_id,
        transaction_type=transaction_type,
        business_metadata=business_metadata,
        created_at=now,
        updated_at=now,
    )


def _make_edi_message(
    trace_id: str = "trace-001",
    direction: str = "OUTBOUND",
    trading_partner_id: str | None = "tp-001",
    connection_type: str | None = "AS2",
) -> EdiMessageDTO:
    now = datetime.now(UTC)
    return EdiMessageDTO(
        id="msg-001",
        trace_id=trace_id,
        direction=direction,
        trading_partner_id=trading_partner_id,
        connection_type=connection_type,
        created_at=now,
        updated_at=now,
    )


def _seed_as2_partner(
    uow: FakeControlPlaneUnitOfWork,
    *,
    partner_id: str,
    as2_id: str,
    name: str,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    uow.as2_partners.partners[partner_id] = AS2Partner(
        id=partner_id,
        tenant_id=PLATFORM_TENANT_ID,
        as2_id=as2_id,
        name=name,
        is_local=False,
        active=True,
        created_at=now,
        updated_at=now,
    )


def _seed_sftp_partner(
    uow: FakeControlPlaneUnitOfWork,
    *,
    partner_id: str,
    name: str,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    uow.sftp_partners.sftp_partners[partner_id] = SFTPPartner(
        id=partner_id,
        tenant_id=TENANT_ID,
        name=name,
        host="sftp.example.com",
        port=22,
        username="edi",
        active=True,
        created_at=now,
        updated_at=now,
    )


class TestResolveRoutingContextMsgAbsent:
    @pytest.mark.asyncio
    async def test_outbound_replay_race_window_returns_without_crash(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        use_case = RoutingResolutionUseCase(uow)
        edi_json = _make_edi_json(direction="OUTBOUND")

        result = await use_case.execute(
            ResolveRoutingContextQuery(
                tenant_id=TENANT_ID,
                edi_message=None,
                edi_jsons=(edi_json,),
            )
        )

        assert result == ResolvedRoutingContextDTO(trading_partner_name=None, connection_type=None)

    @pytest.mark.asyncio
    async def test_outbound_replay_resolves_via_metadata_partner_id(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        now = datetime.now(UTC).replace(tzinfo=None)
        _seed_as2_partner(uow, partner_id="as2-001", as2_id="ACME_AS2", name="Acme Corp")
        uow.outbound_routes.outbound_routes["route-1"] = OutboundRoute(
            id="route-1",
            tenant_id=TENANT_ID,
            trading_partner_id="tp-001",
            name="Acme Outbound",
            active=True,
            as2_partner_id="as2-001",
            created_at=now,
            updated_at=now,
        )

        use_case = RoutingResolutionUseCase(uow)
        edi_json = _make_edi_json(
            direction="OUTBOUND",
            business_metadata={"_routing": {"trading_partner_id": "tp-001"}},
        )

        result = await use_case.execute(
            ResolveRoutingContextQuery(
                tenant_id=TENANT_ID,
                edi_message=None,
                edi_jsons=(edi_json,),
            )
        )

        assert result.trading_partner_name == "Acme Corp"
        assert result.connection_type == ConnectionType.AS2.value

    @pytest.mark.asyncio
    async def test_outbound_replay_falls_back_to_direct_partner_id_in_business_metadata(
        self,
    ) -> None:
        uow = FakeControlPlaneUnitOfWork()
        _seed_sftp_partner(uow, partner_id="sftp-direct", name="Direct SFTP Partner")
        use_case = RoutingResolutionUseCase(uow)
        edi_json = _make_edi_json(
            direction="OUTBOUND",
            business_metadata={"_routing": {"trading_partner_id": "sftp-direct"}},
        )

        result = await use_case.execute(
            ResolveRoutingContextQuery(
                tenant_id=TENANT_ID,
                edi_message=None,
                edi_jsons=(edi_json,),
            )
        )

        assert result.trading_partner_name == "Direct SFTP Partner"
        assert result.connection_type is None

    @pytest.mark.asyncio
    async def test_inbound_replay_race_window_returns_without_crash(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        use_case = RoutingResolutionUseCase(uow)
        edi_json = _make_edi_json(direction="INBOUND")

        result = await use_case.execute(
            ResolveRoutingContextQuery(
                tenant_id=TENANT_ID,
                edi_message=None,
                edi_jsons=(edi_json,),
            )
        )

        assert result == ResolvedRoutingContextDTO(trading_partner_name=None, connection_type=None)

    @pytest.mark.asyncio
    async def test_no_edi_jsons_and_no_msg_returns_empty_context(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        use_case = RoutingResolutionUseCase(uow)

        result = await use_case.execute(
            ResolveRoutingContextQuery(tenant_id=TENANT_ID, edi_message=None, edi_jsons=())
        )

        assert result == ResolvedRoutingContextDTO(trading_partner_name=None, connection_type=None)


class TestResolveOutboundRoutingWithMsg:
    @pytest.mark.asyncio
    async def test_resolves_via_trading_partner_id(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        now = datetime.now(UTC).replace(tzinfo=None)
        _seed_sftp_partner(uow, partner_id="sftp-1", name="Partner A")
        uow.outbound_routes.outbound_routes["route-sftp"] = OutboundRoute(
            id="route-sftp",
            tenant_id=TENANT_ID,
            trading_partner_id="tp-001",
            name="Partner A Route",
            active=True,
            sftp_partner_id="sftp-1",
            created_at=now,
            updated_at=now,
        )

        use_case = RoutingResolutionUseCase(uow)
        msg = _make_edi_message(trading_partner_id="tp-001", connection_type="UNKNOWN")

        result = await use_case.execute(
            ResolveRoutingContextQuery(tenant_id=TENANT_ID, edi_message=msg, edi_jsons=())
        )
        enriched = result.enrich_message(msg)

        assert result.trading_partner_name == "Partner A"
        assert result.connection_type == ConnectionType.SFTP.value
        assert enriched is not None
        assert enriched.connection_type == "SFTP"

    @pytest.mark.asyncio
    async def test_returns_connection_type_when_partner_not_found_in_routes(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        use_case = RoutingResolutionUseCase(uow)
        msg = _make_edi_message(trading_partner_id="tp-999", connection_type="AS2")

        result = await use_case.execute(
            ResolveRoutingContextQuery(tenant_id=TENANT_ID, edi_message=msg, edi_jsons=())
        )

        assert result.trading_partner_name is None
        assert result.connection_type == "AS2"


class TestResolveInboundRoutingWithMsg:
    @pytest.mark.asyncio
    async def test_resolves_via_as2_sender_id(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        _seed_as2_partner(uow, partner_id="as2-in", as2_id="SENDER_AS2_ID", name="AS2 Partner")
        use_case = RoutingResolutionUseCase(uow)
        now = datetime.now(UTC)
        msg = EdiMessageDTO(
            id="msg-001",
            trace_id="trace-001",
            direction="INBOUND",
            connection_type="AS2",
            as2_sender_id="SENDER_AS2_ID",
            created_at=now,
            updated_at=now,
        )

        result = await use_case.execute(
            ResolveRoutingContextQuery(tenant_id=TENANT_ID, edi_message=msg, edi_jsons=())
        )

        assert result.trading_partner_name == "AS2 Partner"
        assert result.connection_type == "AS2"

    @pytest.mark.asyncio
    async def test_resolves_via_inbound_route_sftp_and_webhook(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        now = datetime.now(UTC).replace(tzinfo=None)
        _seed_sftp_partner(uow, partner_id="sftp-in", name="SFTP Partner")
        uow.inbound_routes.inbound_routes["in-route-1"] = InboundRoute(
            id="in-route-1",
            tenant_id=TENANT_ID,
            name="Inbound SFTP",
            isa_sender_id="SENDER-01",
            isa_receiver_id="RECEIVER-01",
            transaction_type="850",
            sftp_partner_id="sftp-in",
            active=True,
            created_at=now,
            updated_at=now,
        )
        uow.webhooks.webhooks["wh-1"] = Webhook(
            id="wh-1",
            tenant_id=TENANT_ID,
            name="ERP Hook",
            url="https://erp.example.com/edi",
            active=True,
            created_at=now,
            updated_at=now,
        )
        uow.inbound_routes.inbound_routes["in-route-wh"] = InboundRoute(
            id="in-route-wh",
            tenant_id=TENANT_ID,
            name="Inbound Webhook",
            isa_sender_id="SENDER-WH",
            isa_receiver_id="RECEIVER-WH",
            transaction_type="810",
            webhook_id="wh-1",
            active=True,
            created_at=now,
            updated_at=now,
        )

        use_case = RoutingResolutionUseCase(uow)
        ts = datetime.now(UTC)
        sftp_msg = EdiMessageDTO(
            id="msg-001",
            trace_id="trace-001",
            direction="INBOUND",
            connection_type="SFTP",
            sender_id="SENDER-01",
            receiver_id="RECEIVER-01",
            created_at=ts,
            updated_at=ts,
        )
        edi_json = _make_edi_json(
            direction="INBOUND", trading_partner_id=None, transaction_type="850"
        )
        sftp_result = await use_case.execute(
            ResolveRoutingContextQuery(
                tenant_id=TENANT_ID,
                edi_message=sftp_msg,
                edi_jsons=(edi_json,),
            )
        )
        assert sftp_result.trading_partner_name == "SFTP Partner"
        assert sftp_result.connection_type == "SFTP"

        wh_msg = EdiMessageDTO(
            id="msg-002",
            trace_id="trace-002",
            direction="INBOUND",
            connection_type="UNKNOWN",
            sender_id="SENDER-WH",
            receiver_id="RECEIVER-WH",
            transaction_type="810",
            created_at=ts,
            updated_at=ts,
        )
        wh_result = await use_case.execute(
            ResolveRoutingContextQuery(tenant_id=TENANT_ID, edi_message=wh_msg, edi_jsons=())
        )
        assert wh_result.trading_partner_name == "https://erp.example.com/edi"
        assert wh_result.connection_type == "WEBHOOK"
        enriched_wh = wh_result.enrich_message(wh_msg)
        assert enriched_wh is not None
        assert enriched_wh.connection_type == "WEBHOOK"

    @pytest.mark.asyncio
    async def test_returns_none_name_and_connection_type_when_no_route_found(self) -> None:
        uow = FakeControlPlaneUnitOfWork()
        use_case = RoutingResolutionUseCase(uow)
        now = datetime.now(UTC)
        msg = EdiMessageDTO(
            id="msg-001",
            trace_id="trace-001",
            direction="INBOUND",
            connection_type="SFTP",
            sender_id="S",
            receiver_id="R",
            created_at=now,
            updated_at=now,
        )

        result = await use_case.execute(
            ResolveRoutingContextQuery(tenant_id=TENANT_ID, edi_message=msg, edi_jsons=())
        )

        assert result.trading_partner_name is None
        assert result.connection_type == "SFTP"
