"""Narrow integration tests for GetConnectionUseCase using real PostgreSQL SAVEPOINTs."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.application.use_cases.connections.create_connection_use_case import (
    CreateConnectionCommand,
    CreateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.get_connection_use_case import (
    GetConnectionQuery,
    GetConnectionUseCase,
)
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix

pytestmark = pytest.mark.integration


@pytest.fixture
def cipher() -> AesGcmCipher:
    key = AesGcmCipher.generate_key()
    return AesGcmCipher(key)


@pytest.mark.asyncio
async def test_get_connection_use_case(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    get_uc = GetConnectionUseCase(uow=uow)

    tenant_id = generate_id(DomainIdPrefix.TENANT.value)
    create_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="itron_mdm",
            name="Get Target",
            auth_type="API_KEY",
            public_config={"endpoint_url": "https://get.grid.com"},
            raw_credentials={"api_key": "k_get"},
            endpoint_for_fingerprint="https://get.grid.com",
        )
    )
    assert create_res.success is True
    assert create_res.connection is not None
    conn_id = create_res.connection.id

    fetched = await get_uc.execute(GetConnectionQuery(tenant_id=tenant_id, connection_id=conn_id))
    assert fetched.success is True
    assert fetched.connection is not None
    assert fetched.connection.id == conn_id

    wrong_tenant = await get_uc.execute(
        GetConnectionQuery(tenant_id="ten_other", connection_id=conn_id)
    )
    assert wrong_tenant.success is False
    assert wrong_tenant.error_code == "CONNECTION_NOT_FOUND"
