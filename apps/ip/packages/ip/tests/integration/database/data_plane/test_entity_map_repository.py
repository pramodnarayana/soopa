"""Narrow Integration Tests for SqlAlchemyGlobalEntityMapRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import TenantSession
from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.domain.normalization.normalized_record import GlobalEntityMap

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_l3_global_entity_map_repository(
    tenant_session: TenantSession,
) -> None:
    gem_repo = SqlAlchemyGlobalEntityMapRepository(tenant_session)
    tenant_id = "ten_dp_l3_gem"

    gem = GlobalEntityMap.create(
        tenant_id=tenant_id,
        trace_id="ip_trc_l3_001",
        entity_domain="SYNTHETIC_ENTITY",
        canonical_id="canon_rec_300",
        source_connection_id="ip_conn_l3",
        source_entity_id="REC-300",
    )
    await gem_repo.save(gem)

    resolved = await gem_repo.get_by_source(
        tenant_id=tenant_id,
        entity_domain="SYNTHETIC_ENTITY",
        source_connection_id="ip_conn_l3",
        source_entity_id="REC-300",
    )
    assert resolved is not None
    assert resolved.canonical_id == "canon_rec_300"
    assert resolved.dest_entity_id is None

    resolved.bind_destination("ip_conn_sink", "SINK-REC-300")
    await gem_repo.save(resolved)

    by_canon = await gem_repo.get_by_canonical_id(tenant_id, "canon_rec_300")
    assert len(by_canon) == 1
    assert by_canon[0].dest_connection_id == "ip_conn_sink"
    assert by_canon[0].dest_entity_id == "SINK-REC-300"
