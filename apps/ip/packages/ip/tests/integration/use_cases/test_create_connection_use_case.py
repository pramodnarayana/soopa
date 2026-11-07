"""Narrow integration tests for CreateConnectionUseCase using real PostgreSQL SAVEPOINTs."""

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
from ip.engine.bootstrap.container import create_ip_control_plane_uow
from ip.engine.domain.exceptions import DuplicateConnectionFingerprintError
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from seedwork import generate_id

pytestmark = pytest.mark.integration


@pytest.fixture
def cipher() -> AesGcmCipher:
    key = AesGcmCipher.generate_key()
    return AesGcmCipher(key)


@pytest.mark.asyncio
async def test_create_connection_use_case(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    repo = SqlAlchemyConnectionRepository(global_session)
    use_case = CreateConnectionUseCase(uow=uow, cipher=cipher)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

    cmd = CreateConnectionCommand(
        tenant_id=tenant_id,
        app_id="acme_source",
        name="Acme Partner Source",
        auth_type="API_KEY",
        public_config={"endpoint_url": "https://api.partner.example.com"},
        raw_credentials={"api_key": "sec_top_secret"},
        endpoint_for_fingerprint="https://api.partner.example.com",
    )

    result = await use_case.execute(cmd)
    assert result.success is True
    assert result.connection is not None
    dto = result.connection

    assert dto.id.startswith("ip_conn_")
    assert dto.tenant_id == tenant_id
    assert dto.name == "Acme Partner Source"
    assert dto.status == "PENDING_AUTH"

    stored = await repo.get_by_id(dto.id)
    assert stored is not None
    assert stored.encrypted_credentials is not None
    assert cipher.decrypt(stored.encrypted_credentials) == {"api_key": "sec_top_secret"}


@pytest.mark.asyncio
async def test_create_duplicate_active_connection_rejected(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    repo = SqlAlchemyConnectionRepository(global_session)
    use_case = CreateConnectionUseCase(uow=uow, cipher=cipher)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

    cmd = CreateConnectionCommand(
        tenant_id=tenant_id,
        app_id="acme_source",
        name="Acme Partner",
        auth_type="API_KEY",
        public_config={"endpoint_url": "https://api.partner.example.com"},
        raw_credentials={"api_key": "sec_1"},
        endpoint_for_fingerprint="https://api.partner.example.com",
    )

    result = await use_case.execute(cmd)
    assert result.success is True
    assert result.connection is not None
    conn = await repo.get_by_id(result.connection.id)
    assert conn is not None
    conn.activate()
    await repo.save(conn)

    dup_result = await use_case.execute(cmd)
    assert dup_result.success is False
    assert dup_result.error_code == "DUPLICATE_FINGERPRINT"
    assert isinstance(dup_result.error, DuplicateConnectionFingerprintError)
    assert "already exists" in (dup_result.error_message or "")
