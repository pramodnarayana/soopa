from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from as2_server.adapters.outbound.database.tenant_routing_repository import (
    SqlAlchemyTenantRoutingRepository,
)
from as2_server.domain.errors import AmbiguousTenantRoutingError


class FakeRowResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def first(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None


class FakeAsyncSession:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._result = FakeRowResult(rows)
        self.statements: list[object] = []

    async def execute(self, statement: object) -> FakeRowResult:
        self.statements.append(statement)
        return self._result


@pytest.mark.asyncio
async def test_resolve_tenant_id_raises_ambiguous_error_when_multiple_matches() -> None:
    session = FakeAsyncSession([("tenant_1",), ("tenant_2",)])
    repo = SqlAlchemyTenantRoutingRepository(cast(AsyncSession, session))
    with pytest.raises(AmbiguousTenantRoutingError, match="Ambiguous tenant routing match"):
        await repo.resolve_tenant_id("SHARED_AS2_ID")
    assert len(session.statements) == 1
    query_str = str(session.statements[0])
    assert "as2_partners.as2_id =" in query_str
    assert "as2_partners.is_local IS true" in query_str


@pytest.mark.asyncio
async def test_resolve_tenant_by_edi_identifiers_raises_ambiguous_error() -> None:
    session = FakeAsyncSession([("tenant_1",), ("tenant_2",)])
    repo = SqlAlchemyTenantRoutingRepository(cast(AsyncSession, session))
    with pytest.raises(AmbiguousTenantRoutingError, match="Ambiguous tenant routing match"):
        await repo.resolve_tenant_by_edi_identifiers(
            as2_peer_id="PEER_AS2",
            isa_sender="SENDER",
            isa_receiver="RECEIVER",
            transaction_type="850",
        )
    assert len(session.statements) == 1
    query_str = str(session.statements[0])
    assert "JOIN edi.as2_partners ON" in query_str
    assert "inbound_routes.isa_sender_id =" in query_str
    assert "inbound_routes.isa_receiver_id =" in query_str
    assert "as2_partners.as2_id =" in query_str


@pytest.mark.asyncio
async def test_resolve_tenant_id_returns_single_match() -> None:
    session = FakeAsyncSession([("tenant_single",)])
    repo = SqlAlchemyTenantRoutingRepository(cast(AsyncSession, session))
    tenant_id = await repo.resolve_tenant_id("UNIQUE_AS2_ID")
    assert tenant_id == "tenant_single"
    assert len(session.statements) == 1
    query_str = str(session.statements[0])
    assert "as2_partners.as2_id =" in query_str
    assert "as2_partners.active IS true" in query_str


@pytest.mark.asyncio
async def test_resolve_tenant_id_returns_none_when_empty() -> None:
    session = FakeAsyncSession([])
    repo = SqlAlchemyTenantRoutingRepository(cast(AsyncSession, session))
    tenant_id = await repo.resolve_tenant_id("NONEXISTENT_AS2_ID")
    assert tenant_id is None
    assert len(session.statements) == 1
