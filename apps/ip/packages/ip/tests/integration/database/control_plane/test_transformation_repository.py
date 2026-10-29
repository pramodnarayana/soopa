"""Narrow Integration Tests for SqlAlchemyTransformationRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.transformation_repository import (
    SqlAlchemyTransformationRepository,
)
from ip.engine.domain.enums import AuthType, TransformationMode
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.normalization import Transformation

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_transformation_repository_save_and_query(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    # 1. Create a parent connection
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Transformation Test Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://ami.test.com"},
        encrypted_credentials=b"dummy_creds",
        endpoint_for_fingerprint="https://ami.test.com",
    )
    save_conn_res = await conn_repo.save(conn)
    assert save_conn_res.is_ok

    repo = SqlAlchemyTransformationRepository(global_session)

    # 2. Save a new transformation
    transformation = Transformation.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="readings",
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        mode=TransformationMode.ACTIVE,
        shadow_transformation_version=2,
    )
    await repo.save(transformation)

    # 3. Query by stream
    fetched = await repo.get_by_stream(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="readings",
    )
    assert fetched is not None
    assert fetched.id == transformation.id
    assert fetched.tenant_id == seeded_ip_tenant
    assert fetched.connection_id == conn.id
    assert fetched.stream == "readings"
    assert fetched.transformation_id == "energy.ami_meter_reading"
    assert fetched.transformation_version == 1
    assert fetched.mode == TransformationMode.ACTIVE
    assert fetched.shadow_transformation_version == 2

    # 4. List by connection
    all_transformations = await repo.list_by_connection(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
    )
    assert len(all_transformations) == 1
    assert all_transformations[0].id == transformation.id

    # 5. Update existing transformation
    updated_transformation = Transformation(
        id=transformation.id,
        tenant_id=transformation.tenant_id,
        connection_id=transformation.connection_id,
        stream=transformation.stream,
        transformation_id=transformation.transformation_id,
        transformation_version=2,
        mode=TransformationMode.SHADOW,
        shadow_transformation_version=None,
        created_at=transformation.created_at,
        updated_at=transformation.updated_at,
    )
    await repo.save(updated_transformation)

    re_fetched = await repo.get_by_stream(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="readings",
    )
    assert re_fetched is not None
    assert re_fetched.transformation_version == 2
    assert re_fetched.mode == TransformationMode.SHADOW
    assert re_fetched.shadow_transformation_version is None
