"""Narrow integration tests for ListConnectionsUseCase using real PostgreSQL SAVEPOINTs."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from identity.domain.constants import IdentityIdPrefix
from ip.engine.application.use_cases.connections.create_connection_use_case import (
    CreateConnectionCommand,
    CreateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.list_connections_use_case import (
    ListConnectionsQuery,
    ListConnectionsUseCase,
)
from ip.engine.bootstrap.container import create_ip_control_plane_uow
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from seedwork import generate_id

pytestmark = pytest.mark.integration


@pytest.fixture
def cipher() -> AesGcmCipher:
    key = AesGcmCipher.generate_key()
    return AesGcmCipher(key)


@pytest.mark.asyncio
async def test_list_connections_use_case(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    list_uc = ListConnectionsUseCase(uow=uow)

    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    create_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="acme_source",
            name="List Target",
            auth_type="API_KEY",
            public_config={"endpoint_url": "https://list.acme.example.com"},
            raw_credentials={"api_key": "k_list"},
            endpoint_for_fingerprint="https://list.acme.example.com",
        )
    )
    assert create_res.success is True
    assert create_res.connection is not None

    listed = await list_uc.execute(ListConnectionsQuery(tenant_id=tenant_id))
    assert len(listed) == 1
    assert listed[0].id == create_res.connection.id
