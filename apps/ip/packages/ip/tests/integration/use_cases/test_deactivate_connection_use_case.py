"""Narrow integration tests for DeactivateConnectionUseCase using real PostgreSQL SAVEPOINTs."""

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
from ip.engine.application.use_cases.connections.deactivate_connection_use_case import (
    DeactivateConnectionCommand,
    DeactivateConnectionUseCase,
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
async def test_deactivate_connection_use_case(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
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

    deact_uc = DeactivateConnectionUseCase(uow=uow)
    deact_res = await deact_uc.execute(
        DeactivateConnectionCommand(connection_id=dto.id, tenant_id=tenant_id)
    )
    assert deact_res.success is True
    assert deact_res.connection is not None
    assert deact_res.connection.status == "DEACTIVATED"
    assert deact_res.connection.deactivated_at is not None


@pytest.mark.asyncio
async def test_deactivate_connection_not_found_returns_failure(
    global_session: GlobalSession,
) -> None:
    uow = SqlAlchemyIpControlPlaneUnitOfWork(global_session)
    deact_uc = DeactivateConnectionUseCase(uow=uow)
    result = await deact_uc.execute(
        DeactivateConnectionCommand(connection_id="missing_id", tenant_id="ten_1")
    )
    assert result.success is False
    assert result.error_code == "CONNECTION_NOT_FOUND"
