"""Narrow Integration Tests for SqlAlchemySyncRunRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.sync_run_repository import (
    SqlAlchemySyncRunRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.domain.enums import AuthType, IpEventType, SyncRunKind, SyncRunStatus
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.sync_run import SyncRun
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_sync_run_repository_lifecycle_and_outbox(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    run_repo = SqlAlchemySyncRunRepository(global_session)

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Sync Run Test Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://syncrun.grid-utility.com"},
        encrypted_credentials=b"secret",
        endpoint_for_fingerprint="https://syncrun.grid-utility.com",
    )
    await conn_repo.save(conn)

    # Default generation is 1 when no runs exist
    initial_gen = await run_repo.get_latest_generation_id(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="meters",
    )
    assert initial_gen == 1

    run = SyncRun.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="meters",
        kind=SyncRunKind.FULL_REFRESH,
        generation_id=2,
        start_checkpoint=None,
    )
    run.start()
    await run_repo.save(run)

    # Active run lookup
    active = await run_repo.get_active_run(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="meters",
    )
    assert active is not None
    assert active.id == run.id
    assert active.status == SyncRunStatus.RUNNING

    # Record page and complete
    active.record_page(
        records_in_page=40,
        bytes_size=4096,
        next_checkpoint="2026-10-23T12:00:00Z",
    )
    active.succeed(end_checkpoint="2026-10-23T12:00:00Z")
    await run_repo.save(active)

    # Active run should now be None
    assert (
        await run_repo.get_active_run(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream="meters",
        )
        is None
    )

    fetched = await run_repo.get_by_id(run.id, seeded_ip_tenant)
    assert fetched is not None
    assert fetched.status == SyncRunStatus.SUCCEEDED
    assert fetched.pages_synced == 1
    assert fetched.records_synced == 40
    assert fetched.bytes_synced == 4096
    assert fetched.end_checkpoint == "2026-10-23T12:00:00Z"

    latest_gen = await run_repo.get_latest_generation_id(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="meters",
    )
    assert latest_gen == 2

    runs_list = await run_repo.list_by_connection(seeded_ip_tenant, conn.id)
    assert len(runs_list) == 1
    assert runs_list[0].id == run.id

    outbox_stmt = select(IpOutboxRecord).where(
        IpOutboxRecord.tenant_id == seeded_ip_tenant,
        IpOutboxRecord.event_type.in_(
            [
                IpEventType.SYNC_RUN_STARTED.value,
                IpEventType.SYNC_RUN_COMPLETED.value,
                IpEventType.GENERATION_COMPLETED.value,
            ]
        ),
    )
    outbox_rows = (await global_session.execute(outbox_stmt)).scalars().all()
    emitted_types = {r.event_type for r in outbox_rows}
    assert IpEventType.SYNC_RUN_STARTED.value in emitted_types
    assert IpEventType.SYNC_RUN_COMPLETED.value in emitted_types
    assert IpEventType.GENERATION_COMPLETED.value in emitted_types
