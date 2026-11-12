"""Narrow Integration Tests for SqlAlchemyConnectionEntityRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.connection_entity_repository import (
    SqlAlchemyConnectionEntityRepository,
)
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType
from ip.engine.domain.connection.stream_schema import StreamField
from ip.engine.domain.enums import IpEventType
from ip.engine.domain.replication.connection_entity import ConnectionEntity
from ip.engine.domain.replication.enums import EntitySyncSchedule, SyncMode
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_connection_entity_repository_persists_subscription_watermarks_with_outbox_events(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    entity_repo = SqlAlchemyConnectionEntityRepository(global_session)

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="acme_source",
        name="Subscribed Entities Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://entities.partner.example.com"},
        encrypted_credentials=b"secret",
        endpoint_for_fingerprint="https://entities.partner.example.com",
    )
    await conn_repo.save(conn)

    entity = ConnectionEntity.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream_name="interval_events",
        sync_mode=SyncMode.INCREMENTAL,
        schedule=EntitySyncSchedule.HOURLY,
        primary_key=["event_id"],
        fields=[StreamField(name="event_id", data_type="string", nullable=False)],
        cursor_field="event_timestamp",
        initial_cursor="2026-10-20T00:00:00Z",
    )
    entity.advance_checkpoint(
        new_cursor_value="2026-10-21T00:00:00Z",
        records_in_batch=250,
    )
    await entity_repo.save(entity)

    fetched = await entity_repo.get_by_stream(seeded_ip_tenant, conn.id, "interval_events")
    assert fetched is not None
    assert fetched.schedule == EntitySyncSchedule.HOURLY
    assert fetched.primary_key == ("event_id",)
    assert fetched.fields[0].name == "event_id"
    assert fetched.cursor_value == "2026-10-21T00:00:00Z"
    assert fetched.records_synced_count == 250

    fetched.advance_checkpoint(
        new_cursor_value="2026-10-22T00:00:00Z",
        records_in_batch=150,
    )
    await entity_repo.save(fetched)

    updated = await entity_repo.get_by_stream(seeded_ip_tenant, conn.id, "interval_events")
    assert updated is not None
    assert updated.cursor_value == "2026-10-22T00:00:00Z"
    assert updated.records_synced_count == 400

    all_entities = await entity_repo.list_by_connection(seeded_ip_tenant, conn.id)
    assert len(all_entities) == 1

    outbox_stmt = select(IpOutboxRecord).where(
        IpOutboxRecord.tenant_id == seeded_ip_tenant,
        IpOutboxRecord.event_type == IpEventType.CONNECTION_ENTITY_CHECKPOINTED.value,
    )
    outbox_rows = (await global_session.execute(outbox_stmt)).scalars().all()
    assert len(outbox_rows) == 2

    await entity_repo.delete(updated)
    after_delete = await entity_repo.list_by_connection(seeded_ip_tenant, conn.id)
    assert len(after_delete) == 0
