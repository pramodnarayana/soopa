"""
Unit tests for RoutingResolutionUseCase.

Critical coverage: the null-EdiMessage paths that occur during the outbound replay
race window (EdiJson committed, EdiMessage not yet created by the transform worker).
These tests would have caught the AttributeError crash that caused the "Not Found"
blank screen before it ever reached production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from edi.application.dtos.transactions import EdiJsonDTO, EdiMessageDTO
from edi.application.use_cases.routing_resolution_use_case import RoutingResolutionUseCase
from edi.ports.outbound.routing_resolver_repository import RoutingResolverRepositoryPort

# ---------------------------------------------------------------------------
# Fake repository
# ---------------------------------------------------------------------------


@dataclass
class FakeRoutingResolverRepository(RoutingResolverRepositoryPort):
    outbound_route: tuple[str, str] | None = None
    inbound_route: tuple[str, str] | None = None
    as2_route: tuple[str, str] | None = None
    business_metadata_name: str | None = None

    async def resolve_outbound_route(self, trading_partner_id: str) -> tuple[str, str] | None:
        return self.outbound_route

    async def resolve_inbound_route(
        self, sender_id: str, receiver_id: str, transaction_type: str | None
    ) -> tuple[str, str] | None:
        return self.inbound_route

    async def resolve_as2_inbound(self, as2_sender_id: str) -> tuple[str, str] | None:
        return self.as2_route

    async def resolve_business_metadata(self, trading_partner_ids: list[str]) -> str | None:
        return self.business_metadata_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_edi_json(
    trace_id: str = "trace-001",
    direction: str = "OUTBOUND",
    trading_partner_id: str | None = "tp-001",
    is_replay: bool = False,
    original_trace_id: str | None = None,
    business_metadata: dict | None = None,
) -> EdiJsonDTO:
    return EdiJsonDTO(
        id="json-001",
        trace_id=trace_id,
        direction=direction,
        trading_partner_id=trading_partner_id,
        business_metadata=business_metadata,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_edi_message(
    trace_id: str = "trace-001",
    direction: str = "OUTBOUND",
    trading_partner_id: str | None = "tp-001",
    connection_type: str | None = "AS2",
    is_replay: bool = False,
) -> EdiMessageDTO:
    return EdiMessageDTO(
        id="msg-001",
        trace_id=trace_id,
        direction=direction,
        trading_partner_id=trading_partner_id,
        connection_type=connection_type,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Tests: outbound replay race window (msg=None)
# ---------------------------------------------------------------------------


class TestResolveRoutingContextMsgAbsent:
    """
    Covers the outbound replay race window: EdiJson committed first;
    EdiMessage created asynchronously by the transform worker.
    The previous code crashed with AttributeError on msg.connection_type.
    """

    @pytest.mark.asyncio
    async def test_outbound_replay_race_window_returns_without_crash(self):
        """
        REGRESSION: Reproduces the exact scenario that caused the 'Not Found' blank screen.
        msg=None, edi_json direction=OUTBOUND, no routing match.
        Before fix: AttributeError: 'NoneType' object has no attribute 'connection_type'
        After fix:  returns (None, None) gracefully.
        """
        repo = FakeRoutingResolverRepository(outbound_route=None)
        use_case = RoutingResolutionUseCase(repo)
        edi_json = _make_edi_json(
            direction="OUTBOUND",
        )

        result = await use_case.resolve_routing_context(msg=None, edi_jsons=[edi_json])

        assert result == (None, None)

    @pytest.mark.asyncio
    async def test_outbound_replay_resolves_via_metadata_partner_id(self):
        """
        msg=None but edi_json has _routing.trading_partner_id in business_metadata.
        Resolver must find the outbound route from the repository.
        """
        repo = FakeRoutingResolverRepository(outbound_route=("Acme Corp", "AS2"))
        use_case = RoutingResolutionUseCase(repo)
        edi_json = _make_edi_json(
            direction="OUTBOUND",
            business_metadata={"_routing": {"trading_partner_id": "tp-001"}},
        )

        name, conn_type = await use_case.resolve_routing_context(msg=None, edi_jsons=[edi_json])

        assert name == "Acme Corp"
        assert conn_type == "AS2"

    @pytest.mark.asyncio
    async def test_inbound_replay_race_window_returns_without_crash(self):
        """
        msg=None and direction=INBOUND.
        Must not crash on msg.as2_sender_id or msg.sender_id.
        """
        repo = FakeRoutingResolverRepository(inbound_route=None)
        use_case = RoutingResolutionUseCase(repo)
        edi_json = _make_edi_json(
            direction="INBOUND",
        )

        result = await use_case.resolve_routing_context(msg=None, edi_jsons=[edi_json])

        assert result == (None, None)

    @pytest.mark.asyncio
    async def test_no_edi_jsons_and_no_msg_returns_none_tuple(self):
        """
        Edge case: both msg and edi_jsons absent. Must not crash.
        """
        repo = FakeRoutingResolverRepository()
        use_case = RoutingResolutionUseCase(repo)

        result = await use_case.resolve_routing_context(msg=None, edi_jsons=[])

        assert result == (None, None)


# ---------------------------------------------------------------------------
# Tests: normal outbound with EdiMessage present
# ---------------------------------------------------------------------------


class TestResolveOutboundRoutingWithMsg:
    @pytest.mark.asyncio
    async def test_resolves_via_trading_partner_id(self):
        repo = FakeRoutingResolverRepository(outbound_route=("Partner A", "SFTP"))
        use_case = RoutingResolutionUseCase(repo)
        msg = _make_edi_message(trading_partner_id="tp-001", connection_type="SFTP")

        name, conn_type = await use_case.resolve_routing_context(msg=msg, edi_jsons=[])

        assert name == "Partner A"
        assert conn_type == "SFTP"

    @pytest.mark.asyncio
    async def test_returns_connection_type_when_partner_not_found_in_routes(self):
        repo = FakeRoutingResolverRepository(outbound_route=None)
        use_case = RoutingResolutionUseCase(repo)
        msg = _make_edi_message(trading_partner_id="tp-999", connection_type="AS2")

        name, conn_type = await use_case.resolve_routing_context(msg=msg, edi_jsons=[])

        assert name is None
        assert conn_type == "AS2"

    @pytest.mark.asyncio
    async def test_is_replay_flag_does_not_affect_routing_resolution(self):
        """
        A replayed transaction with a full EdiMessage (retry_deliver path)
        must resolve routing identically to a non-replayed transaction.
        """
        repo = FakeRoutingResolverRepository(outbound_route=("Partner B", "AS2"))
        use_case = RoutingResolutionUseCase(repo)
        msg = _make_edi_message(
            trading_partner_id="tp-001",
        )

        name, conn_type = await use_case.resolve_routing_context(msg=msg, edi_jsons=[])

        assert name == "Partner B"
        assert conn_type == "AS2"


# ---------------------------------------------------------------------------
# Tests: normal inbound with EdiMessage present
# ---------------------------------------------------------------------------


class TestResolveInboundRoutingWithMsg:
    @pytest.mark.asyncio
    async def test_resolves_via_as2_sender_id(self):
        repo = FakeRoutingResolverRepository(as2_route=("AS2 Partner", "AS2"))
        use_case = RoutingResolutionUseCase(repo)
        msg = EdiMessageDTO(
            id="msg-001",
            trace_id="trace-001",
            direction="INBOUND",
            connection_type="AS2",
            as2_sender_id="SENDER_AS2_ID",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        name, conn_type = await use_case.resolve_routing_context(msg=msg, edi_jsons=[])

        assert name == "AS2 Partner"
        assert conn_type == "AS2"

    @pytest.mark.asyncio
    async def test_resolves_via_inbound_route_when_as2_absent(self):
        repo = FakeRoutingResolverRepository(as2_route=None, inbound_route=("SFTP Partner", "SFTP"))
        use_case = RoutingResolutionUseCase(repo)
        msg = EdiMessageDTO(
            id="msg-001",
            trace_id="trace-001",
            direction="INBOUND",
            connection_type="SFTP",
            sender_id="SENDER-01",
            receiver_id="RECEIVER-01",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        edi_json = _make_edi_json(direction="INBOUND", trading_partner_id=None)

        name, _conn_type = await use_case.resolve_routing_context(msg=msg, edi_jsons=[edi_json])

        assert name == "SFTP Partner"

    @pytest.mark.asyncio
    async def test_returns_none_name_and_connection_type_when_no_route_found(self):
        repo = FakeRoutingResolverRepository(as2_route=None, inbound_route=None)
        use_case = RoutingResolutionUseCase(repo)
        msg = EdiMessageDTO(
            id="msg-001",
            trace_id="trace-001",
            direction="INBOUND",
            connection_type="SFTP",
            sender_id="S",
            receiver_id="R",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        name, conn_type = await use_case.resolve_routing_context(msg=msg, edi_jsons=[])

        assert name is None
        assert conn_type == "SFTP"
