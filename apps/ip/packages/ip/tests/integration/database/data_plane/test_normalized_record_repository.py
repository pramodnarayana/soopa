"""Narrow Integration Tests for SqlAlchemyNormalizedRecordRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import TenantSession
from ip.application.domains.energy.canonical import EnergyEntityType
from ip.engine.adapters.outbound.database.data_plane.normalized_record_repository import (
    SqlAlchemyNormalizedRecordRepository,
)
from ip.engine.domain.models.normalized_record import NormalizedRecord

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_l3_normalized_record_repository(
    tenant_session: TenantSession,
) -> None:
    norm_repo = SqlAlchemyNormalizedRecordRepository(tenant_session)
    tenant_id = "ten_dp_l3"

    norm = NormalizedRecord.create(
        tenant_id=tenant_id,
        connection_id="ip_conn_l3",
        canonical_type=EnergyEntityType.MDM_METER_READING,
        source_id="MTR-300",
        canonical_data={"meter_serial_number": "MTR-300", "kwh_delivered": 55.2},
        trace_id="ip_trc_l3_001",
    )
    await norm_repo.save(norm)

    fetched_norm = await norm_repo.get_by_id(norm.id, tenant_id)
    assert fetched_norm is not None
    assert fetched_norm.canonical_type == EnergyEntityType.MDM_METER_READING

    by_source = await norm_repo.list_by_source(
        tenant_id=tenant_id,
        canonical_type=EnergyEntityType.MDM_METER_READING,
        source_id="MTR-300",
    )
    assert len(by_source) == 1
