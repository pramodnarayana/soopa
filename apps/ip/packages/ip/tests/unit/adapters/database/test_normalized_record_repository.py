"""Pure zero-mock Data Mapper unit tests for SqlAlchemyNormalizedRecordRepository."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.data_plane.normalized_record_repository import (
    SqlAlchemyNormalizedRecordRepository,
)
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.solutions.domains.energy.canonical import EnergyEntityType


def test_normalized_record_mapper_roundtrip() -> None:
    norm = NormalizedRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        canonical_type=EnergyEntityType.MDM_SERVICE_POINT,
        source_id="SP-100",
        canonical_data={"service_point_external_id": "SP-100"},
        trace_id="trc_01",
    )
    norm_orm = SqlAlchemyNormalizedRecordRepository._to_orm_model(norm)
    norm_restored = SqlAlchemyNormalizedRecordRepository._to_domain_model(norm_orm)
    assert norm_restored.id == norm.id
    assert norm_restored.canonical_type == EnergyEntityType.MDM_SERVICE_POINT
