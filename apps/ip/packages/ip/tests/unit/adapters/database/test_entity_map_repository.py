"""Pure zero-mock Data Mapper unit tests for SqlAlchemyGlobalEntityMapRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.data_plane.entity_map_repository import (
    SqlAlchemyGlobalEntityMapRepository,
)
from ip.engine.adapters.outbound.database.models.data_plane import GlobalEntityMapModel


def test_entity_map_mapper_updates_record_from_domain() -> None:
    now = datetime.now(UTC)
    gem_orm = GlobalEntityMapModel(
        id="ip_gem_01",
        tenant_id="ten_01",
        trace_id="trc_01",
        correlation_id=None,
        parent_trace_id=None,
        original_trace_id=None,
        replay_count=0,
        entity_domain="SYNTHETIC_ENTITY",
        canonical_id="canon_01",
        source_connection_id="conn_src",
        source_entity_id="SRC-01",
        dest_connection_id=None,
        dest_entity_id=None,
        created_at=now,
    )
    gem = SqlAlchemyGlobalEntityMapRepository._to_domain_model(gem_orm)
    gem.bind_destination("conn_sink", "SINK-01")
    SqlAlchemyGlobalEntityMapRepository._update_record_from_domain(gem_orm, gem)

    assert gem_orm.dest_connection_id == "conn_sink"
    assert gem_orm.dest_entity_id == "SINK-01"
