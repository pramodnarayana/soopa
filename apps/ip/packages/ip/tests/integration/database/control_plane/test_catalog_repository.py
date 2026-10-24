"""Narrow Integration Tests for SqlAlchemyCatalogRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.catalog_repository import (
    SqlAlchemyCatalogRepository,
)
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.domain.enums import AuthType, SyncMode
from ip.engine.domain.models.catalog import (
    ConnectionCatalog,
    StreamField,
    StreamSchema,
)
from ip.engine.domain.models.connection import Connection

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_catalog_repository_versioning_and_active_resolution(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    cat_repo = SqlAlchemyCatalogRepository(global_session)

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Catalog Test Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://catalog.grid-utility.com"},
        encrypted_credentials=b"secret",
        endpoint_for_fingerprint="https://catalog.grid-utility.com",
    )
    await conn_repo.save(conn)

    cat_v1 = ConnectionCatalog.create(
        connection_id=conn.id,
        catalog_version=1,
        streams=[
            StreamSchema(
                name="meters",
                fields=[StreamField(name="meter_id", data_type="string", nullable=False)],
                primary_key=["meter_id"],
                cursor_field="updated_at",
                supported_sync_modes=[SyncMode.FULL_REFRESH, SyncMode.INCREMENTAL],
            )
        ],
    )
    await cat_repo.save(cat_v1)

    cat_v2 = ConnectionCatalog.create(
        connection_id=conn.id,
        catalog_version=2,
        streams=[
            StreamSchema(
                name="meters",
                fields=[
                    StreamField(name="meter_id", data_type="string", nullable=False),
                    StreamField(name="grid_zone", data_type="string", nullable=True),
                ],
                primary_key=["meter_id"],
                cursor_field="updated_at",
                supported_sync_modes=[SyncMode.FULL_REFRESH, SyncMode.INCREMENTAL],
            )
        ],
    )
    await cat_repo.save(cat_v2)

    latest_active = await cat_repo.get_active_by_connection_id(conn.id)
    assert latest_active is not None
    assert latest_active.catalog_version == 2
    assert len(latest_active.streams[0].fields) == 2

    v1_fetched = await cat_repo.get_by_version(conn.id, 1)
    assert v1_fetched is not None
    assert v1_fetched.catalog_version == 1
    assert len(v1_fetched.streams[0].fields) == 1
