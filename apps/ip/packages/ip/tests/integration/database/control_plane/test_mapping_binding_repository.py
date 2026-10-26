"""Narrow Integration Tests for SqlAlchemyMappingBindingRepository against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.mapping_binding_repository import (
    SqlAlchemyMappingBindingRepository,
)
from ip.engine.domain.enums import AuthType, MappingMode
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.normalization import MappingBinding

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_mapping_binding_repository_save_and_query(
    global_session: GlobalSession,
    seeded_ip_tenant: str,
) -> None:
    # 1. Create a parent connection
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="itron_mdm",
        name="Binding Test Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://ami.test.com"},
        encrypted_credentials=b"dummy_creds",
        endpoint_for_fingerprint="https://ami.test.com",
    )
    save_conn_res = await conn_repo.save(conn)
    assert save_conn_res.is_ok

    repo = SqlAlchemyMappingBindingRepository(global_session)

    # 2. Save a new mapping binding
    binding = MappingBinding.create(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        mode=MappingMode.ACTIVE,
        shadow_mapping_version=2,
    )
    await repo.save(binding)

    # 3. Query by stream
    fetched = await repo.get_by_stream(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="readings",
    )
    assert fetched is not None
    assert fetched.id == binding.id
    assert fetched.tenant_id == seeded_ip_tenant
    assert fetched.connection_id == conn.id
    assert fetched.stream == "readings"
    assert fetched.mapping_id == "energy.ami_meter_reading"
    assert fetched.mapping_version == 1
    assert fetched.mode == MappingMode.ACTIVE
    assert fetched.shadow_mapping_version == 2

    # 4. List by connection
    all_bindings = await repo.list_by_connection(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
    )
    assert len(all_bindings) == 1
    assert all_bindings[0].id == binding.id

    # 5. Update existing binding
    updated_binding = MappingBinding(
        id=binding.id,
        tenant_id=binding.tenant_id,
        connection_id=binding.connection_id,
        stream=binding.stream,
        mapping_id=binding.mapping_id,
        mapping_version=2,
        mode=MappingMode.SHADOW,
        shadow_mapping_version=None,
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )
    await repo.save(updated_binding)

    re_fetched = await repo.get_by_stream(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        stream="readings",
    )
    assert re_fetched is not None
    assert re_fetched.mapping_version == 2
    assert re_fetched.mode == MappingMode.SHADOW
    assert re_fetched.shadow_mapping_version is None
