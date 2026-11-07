"""Unit tests for GlobalEntityMap domain aggregate."""

from __future__ import annotations

from ip.engine.domain.normalization.normalized_record import GlobalEntityMap
from strace.domain import TracedAggregateRoot


def test_global_entity_map_create_initializes_unmapped_destination() -> None:
    gem = GlobalEntityMap.create(
        tenant_id="ten_01",
        trace_id="ip_trc_03",
        entity_domain="SYNTHETIC_ENTITY",
        canonical_id="entity_canon_01",
        source_connection_id="ip_conn_src",
        source_entity_id="SRC-ENT-900",
        correlation_id="corr-ent-01",
    )

    assert isinstance(gem, TracedAggregateRoot)
    assert gem.id.startswith("ip_gem_")
    assert gem.trace_id == "ip_trc_03"
    assert gem.dest_connection_id is None
    assert gem.dest_entity_id is None


def test_global_entity_map_bind_destination_sets_destination_identifiers() -> None:
    gem = GlobalEntityMap.create(
        tenant_id="ten_01",
        trace_id="ip_trc_03",
        entity_domain="SYNTHETIC_ENTITY",
        canonical_id="entity_canon_01",
        source_connection_id="ip_conn_src",
        source_entity_id="SRC-ENT-900",
        correlation_id="corr-ent-01",
    )

    gem.bind_destination(
        dest_connection_id="ip_conn_sf",
        dest_entity_id="SF-OBJ-777",
    )
    assert gem.dest_connection_id == "ip_conn_sf"
    assert gem.dest_entity_id == "SF-OBJ-777"
