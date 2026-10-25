"""Pure zero-mock Data Mapper unit tests for SqlAlchemyReplicaRecordRepository."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.adapters.outbound.database.models.data_plane import ReplicaRecordModel
from ip.engine.domain.models.replica_record import ReplicaRecord


def test_replica_record_mapper_and_update_record_from_domain() -> None:
    now = datetime.now(UTC)
    orm = ReplicaRecordModel(
        id="ip_rep_01",
        tenant_id="ten_01",
        trace_id="trc_01",
        correlation_id="corr_01",
        connection_id="conn_01",
        stream="meter",
        record_key="MTR-01",
        primary_key_values=["MTR-01"],
        cursor_value="100",
        cursor_kind="INTEGER",
        data={"kwh": 10.0},
        data_hash="h1",
        version=1,
        generation_id=1,
        last_seen_generation=1,
        first_seen_at=now,
        extracted_at=now,
        updated_at=now,
        deleted_at=None,
        source_inbound_record_id="inb_01",
    )

    domain = SqlAlchemyReplicaRecordRepository._to_domain_model(orm)
    assert domain.id == "ip_rep_01"
    assert domain.version == 1
    assert domain.stream == "meter"
    assert domain.record_key == "MTR-01"
    assert domain.cursor_value == "100"

    updated_domain = ReplicaRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meter",
        record_key="MTR-01",
        data={"kwh": 25.0},
        trace_id="trc_02",
    )
    updated_domain.version = 2
    SqlAlchemyReplicaRecordRepository._update_record_from_domain(orm, updated_domain)

    assert orm.data == {"kwh": 25.0}
    assert orm.version == 2
    assert orm.trace_id == "trc_02"
