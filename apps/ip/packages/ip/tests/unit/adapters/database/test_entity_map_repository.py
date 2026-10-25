"""Pure zero-mock Data Mapper unit tests for SqlAlchemyGlobalEntityMapRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.adapters.outbound.database.models.data_plane import GlobalEntityMapModel


def test_entity_map_mapper_and_update_record_from_domain() -> None:
    now = datetime.now(UTC)
    gem_orm = GlobalEntityMapModel(
        id="ip_gem_01",
        tenant_id="ten_01",
        trace_id="trc_01",
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        entity_domain="TMS_LOAD",
        canonical_id="load_01",
        source_connection_id="conn_mg",
        source_entity_id="MG-01",
        dest_connection_id=None,
        dest_entity_id=None,
        created_at=now,
    )
    gem = SqlAlchemyGlobalEntityMapRepository._to_domain_model(gem_orm)
    gem.bind_destination("conn_sf", "SF-01")
    SqlAlchemyGlobalEntityMapRepository._update_record_from_domain(gem_orm, gem)

    assert gem_orm.dest_connection_id == "conn_sf"
    assert gem_orm.dest_entity_id == "SF-01"
