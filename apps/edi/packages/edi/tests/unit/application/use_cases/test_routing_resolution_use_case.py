"""
Layer 2 — Application Use Case Tests: RoutingResolutionUseCase.

Injects a fake RoutingResolverRepositoryPort. No database, no HTTP.
Tests all routing resolution branches: outbound, inbound, business metadata
fallback, AS2 partner resolution, and error recovery.
"""

import pytest

from edi.application.use_cases.routing_resolution_use_case import RoutingResolutionUseCase
from edi.domain.models import ConnectionType, Direction

# ---------------------------------------------------------------------------
# Fake Port Implementation
# ---------------------------------------------------------------------------


class FakeRoutingResolverRepository:
    def __init__(self):
        self._outbound_routes: dict[str, tuple[str, str] | None] = {}
        self._as2_inbound: dict[str, tuple[str, str] | None] = {}
        self._inbound_routes: dict[tuple, tuple[str, str] | None] = {}
        self._business_metadata: dict[str, str | None] = {}
        self.call_log: list[str] = []

    def seed_outbound_route(self, tp_id: str, result: tuple[str, str] | None):
        self._outbound_routes[tp_id] = result

    def seed_as2_inbound(self, as2_from: str, result: tuple[str, str] | None):
        self._as2_inbound[as2_from] = result

    def seed_inbound_route(
        self, sender_id: str, receiver_id: str, t_type: str | None, result: tuple[str, str] | None
    ):
        self._inbound_routes[(sender_id, receiver_id, t_type)] = result

    def seed_business_metadata(self, partner_ids: list[str], result: str | None):
        for pid in partner_ids:
            self._business_metadata[pid] = result

    async def resolve_outbound_route(self, tp_id: str) -> tuple[str, str] | None:
        self.call_log.append(f"resolve_outbound_route:{tp_id}")
        return self._outbound_routes.get(tp_id)

    async def resolve_as2_inbound(self, as2_from: str) -> tuple[str, str] | None:
        self.call_log.append(f"resolve_as2_inbound:{as2_from}")
        return self._as2_inbound.get(as2_from)

    async def resolve_inbound_route(
        self, sender_id: str, receiver_id: str, t_type: str | None
    ) -> tuple[str, str] | None:
        self.call_log.append(f"resolve_inbound_route:{sender_id}:{receiver_id}")
        return self._inbound_routes.get((sender_id, receiver_id, t_type))

    async def resolve_business_metadata(self, partner_ids: list[str]) -> str | None:
        self.call_log.append(f"resolve_business_metadata:{partner_ids}")
        for pid in partner_ids:
            result = self._business_metadata.get(pid)
            if result is not None:
                return result
        return None


# ---------------------------------------------------------------------------
# Test doubles for message and edi_json objects
# ---------------------------------------------------------------------------


class FakeMsg:
    def __init__(
        self,
        direction=Direction.INBOUND,
        connection_type=ConnectionType.AS2,
        trading_partner_id=None,
        as2_sender_id=None,
        sender_id="S1",
        receiver_id="R1",
        trace_id="trace-001",
    ):
        self.direction = direction
        self.connection_type = connection_type
        self.trading_partner_id = trading_partner_id
        self.as2_sender_id = as2_sender_id
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.trace_id = trace_id


class FakeEdiJson:
    def __init__(self, transaction_type="850", business_metadata=None):
        self.transaction_type = transaction_type
        self.business_metadata = business_metadata or {}


# ---------------------------------------------------------------------------
# Outbound routing tests
# ---------------------------------------------------------------------------


class TestRoutingResolutionOutbound:
    def setup_method(self):
        self.repo = FakeRoutingResolverRepository()
        self.use_case = RoutingResolutionUseCase(repository=self.repo)

    @pytest.mark.asyncio
    async def test_resolves_outbound_by_trading_partner_id(self):
        self.repo.seed_outbound_route("tp_001", ("TradingCo", "AS2"))
        msg = FakeMsg(direction=Direction.OUTBOUND, trading_partner_id="tp_001")
        name, conn_type = await self.use_case.resolve_routing_context(msg, [])
        assert name == "TradingCo"
        assert conn_type == "AS2"

    @pytest.mark.asyncio
    async def test_outbound_falls_back_to_business_metadata_when_no_route(self):
        """trading_partner_id is set but outbound route returns None → try business metadata."""
        self.repo.seed_outbound_route("tp_001", None)
        self.repo.seed_business_metadata(["tp_001"], "MetaPartner")
        msg = FakeMsg(
            direction=Direction.OUTBOUND,
            trading_partner_id="tp_001",
        )
        edi_json = FakeEdiJson(business_metadata={"_routing": {"trading_partner_id": "tp_001"}})
        name, _ = await self.use_case.resolve_routing_context(msg, [edi_json])
        assert name == "MetaPartner"

    @pytest.mark.asyncio
    async def test_outbound_returns_none_when_no_routes_and_no_metadata(self):
        self.repo.seed_outbound_route("tp_001", None)
        msg = FakeMsg(direction=Direction.OUTBOUND, trading_partner_id="tp_001")
        name, _ = await self.use_case.resolve_routing_context(msg, [])
        assert name is None

    @pytest.mark.asyncio
    async def test_outbound_direction_attribute_triggers_outbound_path(self):
        """msg.direction == OUTBOUND even without trading_partner_id → outbound path."""
        msg = FakeMsg(direction=Direction.OUTBOUND, trading_partner_id=None)
        name, _ = await self.use_case.resolve_routing_context(msg, [])
        assert name is None  # no routes seeded; should not crash

    @pytest.mark.asyncio
    async def test_exception_in_outbound_route_is_swallowed_and_falls_back(self):
        """Repository exception must not propagate — just fall back gracefully."""

        class FailingRepo(FakeRoutingResolverRepository):
            async def resolve_outbound_route(self, tp_id: str):
                raise RuntimeError("DB timeout")

        repo = FailingRepo()
        use_case = RoutingResolutionUseCase(repository=repo)
        msg = FakeMsg(direction=Direction.OUTBOUND, trading_partner_id="tp_X")
        # Must not raise
        name, _ = await use_case.resolve_routing_context(msg, [])
        assert name is None


# ---------------------------------------------------------------------------
# Inbound routing tests
# ---------------------------------------------------------------------------


class TestRoutingResolutionInbound:
    def setup_method(self):
        self.repo = FakeRoutingResolverRepository()
        self.use_case = RoutingResolutionUseCase(repository=self.repo)

    @pytest.mark.asyncio
    async def test_resolves_inbound_via_as2_partner(self):
        self.repo.seed_as2_inbound("AS2_FROM_ID", ("AS2Partner", "AS2"))
        msg = FakeMsg(
            direction=Direction.INBOUND,
            connection_type=ConnectionType.AS2,
            as2_sender_id="AS2_FROM_ID",
        )
        name, _ = await self.use_case.resolve_routing_context(msg, [])
        assert name == "AS2Partner"
        assert "resolve_as2_inbound:AS2_FROM_ID" in self.repo.call_log

    @pytest.mark.asyncio
    async def test_resolves_inbound_via_inbound_route_for_non_as2(self):
        self.repo.seed_inbound_route("S1", "R1", "850", ("SFTPPartner", "SFTP"))
        msg = FakeMsg(
            direction=Direction.INBOUND,
            connection_type=ConnectionType.SFTP,
            sender_id="S1",
            receiver_id="R1",
        )
        edi_jsons = [FakeEdiJson(transaction_type="850")]
        name, _ = await self.use_case.resolve_routing_context(msg, edi_jsons)
        assert name == "SFTPPartner"

    @pytest.mark.asyncio
    async def test_inbound_business_metadata_has_priority_over_route(self):
        """If business_metadata._routing.trading_partner_id resolves, it wins first."""
        self.repo.seed_business_metadata(["tp_meta"], "MetaPartner")
        self.repo.seed_inbound_route("S1", "R1", "850", ("RoutePartner", "AS2"))
        msg = FakeMsg(
            direction=Direction.INBOUND,
            connection_type=ConnectionType.AS2,
            sender_id="S1",
            receiver_id="R1",
        )
        edi_json = FakeEdiJson(business_metadata={"_routing": {"trading_partner_id": "tp_meta"}})
        name, _ = await self.use_case.resolve_routing_context(msg, [edi_json])
        assert name == "MetaPartner"

    @pytest.mark.asyncio
    async def test_inbound_returns_connection_type_when_partner_not_resolved(self):
        msg = FakeMsg(
            direction=Direction.INBOUND,
            connection_type=ConnectionType.AS2,
        )
        name, conn_type = await self.use_case.resolve_routing_context(msg, [])
        assert name is None
        assert conn_type == ConnectionType.AS2

    @pytest.mark.asyncio
    async def test_exception_in_inbound_resolution_is_swallowed(self):
        class FailingRepo(FakeRoutingResolverRepository):
            async def resolve_as2_inbound(self, as2_from: str):
                raise RuntimeError("Network error")

            async def resolve_inbound_route(self, s, r, t):
                raise RuntimeError("DB timeout")

        repo = FailingRepo()
        use_case = RoutingResolutionUseCase(repository=repo)
        msg = FakeMsg(
            direction=Direction.INBOUND,
            connection_type=ConnectionType.AS2,
            as2_sender_id="BROKEN_FROM",
        )
        # Must not raise
        name, _ = await use_case.resolve_routing_context(msg, [])
        assert name is None

    @pytest.mark.asyncio
    async def test_empty_edi_jsons_skips_business_metadata_lookup(self):
        msg = FakeMsg(direction=Direction.INBOUND, connection_type=ConnectionType.AS2)
        _name, _ = await self.use_case.resolve_routing_context(msg, [])
        assert "resolve_business_metadata" not in " ".join(self.repo.call_log)

    @pytest.mark.asyncio
    async def test_invalid_partner_id_in_metadata_is_silently_skipped(self):
        """Non-string / non-UUID partner IDs in business metadata should not crash."""
        msg = FakeMsg(direction=Direction.INBOUND)
        # partner_id value that would cause str(pid) to still work fine
        edi_json = FakeEdiJson(business_metadata={"_routing": {"trading_partner_id": None}})
        name, _ = await self.use_case.resolve_routing_context(msg, [edi_json])
        assert name is None
