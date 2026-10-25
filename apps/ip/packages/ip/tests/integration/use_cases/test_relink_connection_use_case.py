"""Narrow integration tests for RelinkConnectionUseCase using real PostgreSQL SAVEPOINTs."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.adapters.outbound.database.control_plane.uow import (
    SqlAlchemyIpControlPlaneUnitOfWork,
)
from ip.engine.application.use_cases.connections.create_connection_use_case import (
    CreateConnectionCommand,
    CreateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.deactivate_connection_use_case import (
    DeactivateConnectionCommand,
    DeactivateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.relink_connection_use_case import (
    RelinkConnectionCommand,
    RelinkConnectionUseCase,
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
async def test_relink_connection_use_case(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    deact_uc = DeactivateConnectionUseCase(uow=uow)
    relink_uc = RelinkConnectionUseCase(uow=uow, cipher=cipher)
    tenant_id = generate_id(DomainIdPrefix.TENANT.value)

    create_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="itron_mdm",
            name="Itron",
            auth_type="API_KEY",
            public_config={"endpoint_url": "https://ami.gridpower.com"},
            raw_credentials={"api_key": "valid_token"},
            endpoint_for_fingerprint="https://ami.gridpower.com",
        )
    )
    assert create_res.success is True
    assert create_res.connection is not None
    dto = create_res.connection

    await deact_uc.execute(DeactivateConnectionCommand(connection_id=dto.id, tenant_id=tenant_id))

    relink_res = await relink_uc.execute(
        RelinkConnectionCommand(
            connection_id=dto.id,
            tenant_id=tenant_id,
            new_name="Itron Resurrected",
            updated_raw_credentials={"api_key": "new_refreshed_key"},
        )
    )
    assert relink_res.success is True
    assert relink_res.connection is not None
    relink_dto = relink_res.connection

    assert relink_dto.status == "ACTIVE"
    assert relink_dto.name == "Itron Resurrected"
    assert relink_dto.deactivated_at is None

    updated_conn = await conn_repo.get_by_id(dto.id)
    assert updated_conn is not None
    assert updated_conn.encrypted_credentials is not None
    assert cipher.decrypt(updated_conn.encrypted_credentials) == {"api_key": "new_refreshed_key"}


@pytest.mark.asyncio
async def test_relink_connection_not_found_returns_failure(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    relink_uc = RelinkConnectionUseCase(uow=uow, cipher=cipher)
    result = await relink_uc.execute(
        RelinkConnectionCommand(connection_id="missing_id", tenant_id="ten_1")
    )
    assert result.success is False
    assert result.error_code == "CONNECTION_NOT_FOUND"
