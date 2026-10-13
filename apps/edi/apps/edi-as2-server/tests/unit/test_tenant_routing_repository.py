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

    async def execute(self, _statement: object) -> FakeRowResult:
        return self._result


@pytest.mark.asyncio
async def test_resolve_tenant_id_raises_ambiguous_error_when_multiple_matches() -> None:
    session = cast(AsyncSession, FakeAsyncSession([("tenant_1",), ("tenant_2",)]))
    repo = SqlAlchemyTenantRoutingRepository(session)
    with pytest.raises(AmbiguousTenantRoutingError, match="Ambiguous tenant routing match"):
        await repo.resolve_tenant_id("SHARED_AS2_ID")


@pytest.mark.asyncio
async def test_resolve_tenant_by_edi_identifiers_raises_ambiguous_error() -> None:
    session = cast(AsyncSession, FakeAsyncSession([("tenant_1",), ("tenant_2",)]))
    repo = SqlAlchemyTenantRoutingRepository(session)
    with pytest.raises(AmbiguousTenantRoutingError, match="Ambiguous tenant routing match"):
        await repo.resolve_tenant_by_edi_identifiers(
            as2_peer_id="PEER_AS2",
            isa_sender="SENDER",
            isa_receiver="RECEIVER",
        )


@pytest.mark.asyncio
async def test_resolve_tenant_id_returns_single_match() -> None:
    session = cast(AsyncSession, FakeAsyncSession([("tenant_single",)]))
    repo = SqlAlchemyTenantRoutingRepository(session)
    tenant_id = await repo.resolve_tenant_id("UNIQUE_AS2_ID")
    assert tenant_id == "tenant_single"


@pytest.mark.asyncio
async def test_resolve_tenant_id_returns_none_when_empty() -> None:
    session = cast(AsyncSession, FakeAsyncSession([]))
    repo = SqlAlchemyTenantRoutingRepository(session)
    tenant_id = await repo.resolve_tenant_id("NONEXISTENT_AS2_ID")
    assert tenant_id is None
