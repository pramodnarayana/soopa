"""Narrow Integration Tests for SqlAlchemyStreamStateRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.stream_state_repository import (
    SqlAlchemyStreamStateRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.domain.enums import AuthType, IpEventType
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.stream_state import ConnectionStreamState
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_stream_state_repository_checkpoint_progression_and_outbox(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    state_repo = SqlAlchemyStreamStateRepository(global_session)

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Stream State Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://state.grid-utility.com"},
        encrypted_credentials=b"secret",
        endpoint_for_fingerprint="https://state.grid-utility.com",
    )
    await conn_repo.save(conn)

    state = ConnectionStreamState.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream_name="interval_reads",
        cursor_field="reading_timestamp",
        initial_cursor="2026-10-20T00:00:00Z",
    )
    state.advance_checkpoint(
        new_cursor_value="2026-10-21T00:00:00Z",
        records_in_batch=250,
    )
    await state_repo.save(state)

    fetched = await state_repo.get_by_stream(seeded_ip_tenant, conn.id, "interval_reads")
    assert fetched is not None
    assert fetched.cursor_value == "2026-10-21T00:00:00Z"
    assert fetched.records_synced_count == 250

    fetched.advance_checkpoint(
        new_cursor_value="2026-10-22T00:00:00Z",
        records_in_batch=150,
    )
    await state_repo.save(fetched)

    updated = await state_repo.get_by_stream(seeded_ip_tenant, conn.id, "interval_reads")
    assert updated is not None
    assert updated.cursor_value == "2026-10-22T00:00:00Z"
    assert updated.records_synced_count == 400

    all_states = await state_repo.list_by_connection(seeded_ip_tenant, conn.id)
    assert len(all_states) == 1

    outbox_stmt = select(IpOutboxRecord).where(
        IpOutboxRecord.tenant_id == seeded_ip_tenant,
        IpOutboxRecord.event_type == IpEventType.STREAM_STATE_CHECKPOINTED.value,
    )
    outbox_rows = (await global_session.execute(outbox_stmt)).scalars().all()
    assert len(outbox_rows) == 2
