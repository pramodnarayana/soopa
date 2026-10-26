"""Unit tests for GlobalEntityMap domain aggregate."""

from __future__ import annotations

from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from strace.domain import TracedAggregateRoot


def test_global_entity_map_create_and_bind_destination() -> None:
    gem = GlobalEntityMap.create(
        tenant_id="ten_01",
        trace_id="ip_trc_03",
        entity_domain="TMS_LOAD",
        canonical_id="load_canon_01",
        source_connection_id="ip_conn_mg",
        source_entity_id="MG-LOAD-900",
        correlation_id="corr-tms-01",
    )

    assert isinstance(gem, TracedAggregateRoot)
    assert gem.id.startswith("ip_gem_")
    assert gem.trace_id == "ip_trc_03"
    assert gem.dest_connection_id is None
    assert gem.dest_entity_id is None

    gem.bind_destination(
        dest_connection_id="ip_conn_sf",
        dest_entity_id="SF-OBJ-777",
    )
    assert gem.dest_connection_id == "ip_conn_sf"
    assert gem.dest_entity_id == "SF-OBJ-777"
