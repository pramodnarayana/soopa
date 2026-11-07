"""Narrow Integration Tests for SqlAlchemyShardedTraceRetentionRepository against real PostgreSQL.

Runs inside SAVEPOINT-isolated transactions (`transactional_router`, `tenant_session`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from database.testing import TransactionalTestRouter
from database.types import TenantSession
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpProcessedEventModel,
    IpTraceEventModel,
)
from ip.engine.domain.trace.enums import IpTraceEventType
from sqlalchemy import select
from strace.adapters.retention_repository import SqlAlchemyShardedTraceRetentionRepository
from strace.application.clean_trace_retention_use_case import (
    CleanTraceRetentionCommand,
    CleanTraceRetentionUseCase,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_sharded_trace_retention_repository_prunes_expired_retention_tables(
    seeded_ip_tenant: str,
    tenant_session: TenantSession,
    transactional_router: TransactionalTestRouter,
) -> None:
    """Verify CleanTraceRetentionUseCase prunes expired ip_trace_events and ip_processed_events."""
    expired_ts = datetime.now(UTC) - timedelta(days=45)
    recent_ts = datetime.now(UTC) - timedelta(days=1)

    tenant_session.add_all(
        [
            IpTraceEventModel(
                id="tr_evt_old_1",
                tenant_id=seeded_ip_tenant,
                trace_id="tr_old",
                correlation_id="corr_old",
                event_type=IpTraceEventType.INGEST_RECEIVED.value,
                actor="SYSTEM",
                metadata_={"summary": "Old trace event"},
                created_at=expired_ts,
            ),
            IpTraceEventModel(
                id="tr_evt_recent_1",
                tenant_id=seeded_ip_tenant,
                trace_id="tr_recent",
                correlation_id="corr_recent",
                event_type=IpTraceEventType.INGEST_RECEIVED.value,
                actor="SYSTEM",
                metadata_={"summary": "Recent trace event"},
                created_at=recent_ts,
            ),
            IpProcessedEventModel(
                idempotency_key="idem_old_1",
                tenant_id=seeded_ip_tenant,
                processed_at=expired_ts,
            ),
            IpProcessedEventModel(
                idempotency_key="idem_recent_1",
                tenant_id=seeded_ip_tenant,
                processed_at=recent_ts,
            ),
        ]
    )
    await tenant_session.flush()

    retention_repo = SqlAlchemyShardedTraceRetentionRepository(
        transactional_router,
        app_slug="ip",
        trace_event_model_cls=IpTraceEventModel,
        processed_event_model_cls=IpProcessedEventModel,
    )
    use_case = CleanTraceRetentionUseCase(repository=retention_repo)
    result = await use_case.execute(
        CleanTraceRetentionCommand(
            trace_retention_days=30,
            processed_event_retention_days=14,
        )
    )
    assert result.trace_events_deleted >= 1
    assert result.processed_events_deleted >= 1

    remaining_trace_ids = (
        (
            await tenant_session.execute(
                select(IpTraceEventModel.id).where(IpTraceEventModel.tenant_id == seeded_ip_tenant)
            )
        )
        .scalars()
        .all()
    )
    assert "tr_evt_old_1" not in remaining_trace_ids
    assert "tr_evt_recent_1" in remaining_trace_ids

    remaining_idem_keys = (
        (
            await tenant_session.execute(
                select(IpProcessedEventModel.idempotency_key).where(
                    IpProcessedEventModel.tenant_id == seeded_ip_tenant
                )
            )
        )
        .scalars()
        .all()
    )
    assert "idem_old_1" not in remaining_idem_keys
    assert "idem_recent_1" in remaining_idem_keys
