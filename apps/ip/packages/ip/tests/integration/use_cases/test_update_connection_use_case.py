"""Narrow integration tests for UpdateConnectionUseCase using real PostgreSQL SAVEPOINTs."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from identity.domain.constants import IdentityIdPrefix
from ip.engine.adapters.outbound.database.control_plane.connection_repository import (
    SqlAlchemyConnectionRepository,
)
from ip.engine.application.use_cases.connections.create_connection_use_case import (
    CreateConnectionCommand,
    CreateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.deactivate_connection_use_case import (
    DeactivateConnectionCommand,
    DeactivateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.update_connection_use_case import (
    UpdateConnectionCommand,
    UpdateConnectionUseCase,
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
async def test_update_connection_use_case_updates_metadata(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    conn_repo = SqlAlchemyConnectionRepository(global_session)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    update_uc = UpdateConnectionUseCase(uow=uow, cipher=cipher)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

    create_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="acme_source",
            name="Acme Source",
            auth_type="API_KEY",
            public_config={"endpoint_url": "https://api.partner.example.com"},
            raw_credentials={"api_key": "valid_token"},
            endpoint_for_fingerprint="https://api.partner.example.com",
        )
    )
    assert create_res.success is True
    assert create_res.connection is not None
    dto = create_res.connection

    update_res = await update_uc.execute(
        UpdateConnectionCommand(
            connection_id=dto.id,
            tenant_id=tenant_id,
            new_name="Acme Source Renamed",
            updated_raw_credentials={"api_key": "updated_key"},
            updated_public_config={"endpoint_url": "https://api.partner.example.com/v2"},
        )
    )
    assert update_res.success is True
    assert update_res.connection is not None
    update_dto = update_res.connection

    assert update_dto.status == "PENDING_AUTH"
    assert update_dto.name == "Acme Source Renamed"
    assert update_dto.public_config == {"endpoint_url": "https://api.partner.example.com/v2"}

    updated_conn = await conn_repo.get_by_id(dto.id)
    assert updated_conn is not None
    assert updated_conn.encrypted_credentials is not None
    assert cipher.decrypt(updated_conn.encrypted_credentials) == {"api_key": "updated_key"}


@pytest.mark.asyncio
async def test_update_connection_use_case_deactivated_connection_returns_invalid_state(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    deact_uc = DeactivateConnectionUseCase(uow=uow)
    update_uc = UpdateConnectionUseCase(uow=uow, cipher=cipher)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

    create_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="acme_source",
            name="Acme Source",
            auth_type="API_KEY",
            public_config={"endpoint_url": "https://api.partner.example.com"},
            raw_credentials={"api_key": "valid_token"},
            endpoint_for_fingerprint="https://api.partner.example.com",
        )
    )
    assert create_res.success is True
    assert create_res.connection is not None
    dto = create_res.connection

    await deact_uc.execute(DeactivateConnectionCommand(connection_id=dto.id, tenant_id=tenant_id))

    update_res = await update_uc.execute(
        UpdateConnectionCommand(
            connection_id=dto.id,
            tenant_id=tenant_id,
            new_name="Should Fail Update",
        )
    )
    assert update_res.success is False
    assert update_res.error_code == "INVALID_CONNECTION_STATE"


@pytest.mark.asyncio
async def test_update_connection_use_case_not_found_returns_failure(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    update_uc = UpdateConnectionUseCase(uow=uow, cipher=cipher)
    result = await update_uc.execute(
        UpdateConnectionCommand(connection_id="missing_id", tenant_id="ten_1")
    )
    assert result.success is False
    assert result.error_code == "CONNECTION_NOT_FOUND"
