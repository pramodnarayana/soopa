"""Pure unit tests for UpdateConnectionUseCase using in-memory Control Plane UoW."""

from __future__ import annotations

from types import TracebackType

import pytest
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dtos.connection_dtos import UpdateConnectionHttpRequest
from ip.engine.adapters.inbound.api.routers.connections_router import update_connection
from ip.engine.application.use_cases.connections.update_connection_use_case import (
    UpdateConnectionCommand,
    UpdateConnectionUseCase,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.exceptions import (
    ConnectionNotFoundError,
    DuplicateConnectionFingerprintError,
    InvalidConnectionStateError,
    Result,
)
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.transformation_repository_port import TransformationRepositoryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from seedwork.events import EventEnvelope


class _FakeConnectionRepo(ConnectionRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, Connection] = {}

    async def save(
        self, connection: Connection
    ) -> Result[Connection, DuplicateConnectionFingerprintError]:
        self.items[connection.id] = connection
        return Result.ok(connection)

    async def get_by_id(self, connection_id: str) -> Connection | None:
        return self.items.get(connection_id)

    async def get_by_fingerprint(self, tenant_id: str, fingerprint: str) -> Connection | None:
        return None

    async def list_by_tenant(
        self, tenant_id: str, status: ConnectionStatus | None = None
    ) -> list[Connection]:
        return [c for c in self.items.values() if c.tenant_id == tenant_id]


class _FakeControlPlaneUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: TransformationRepositoryPort
    stitches: StitchRepositoryPort

    def __init__(self) -> None:
        self.connections = _FakeConnectionRepo()
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> _FakeControlPlaneUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        _ = (tenant_id, idempotency_key)
        return True

    async def release_idempotency(self, tenant_id: str, idempotency_key: str) -> None:
        _ = (tenant_id, idempotency_key)

    async def stage_outbox_envelope(self, envelope: EventEnvelope) -> None:
        _ = envelope


@pytest.fixture
def cipher() -> AesGcmCipher:
    key = AesGcmCipher.generate_key()
    return AesGcmCipher(key)


@pytest.mark.asyncio
async def test_update_connection_use_case_updates_metadata_successfully(
    cipher: AesGcmCipher,
) -> None:
    uow = _FakeControlPlaneUoW()
    conn = Connection.create(
        tenant_id="ten_01",
        app_id="acme_app",
        name="Original Acme",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.acme.example.com"},
        encrypted_credentials=b"old_creds",
        endpoint_for_fingerprint="https://api.acme.example.com",
    )
    conn.status = ConnectionStatus.ACTIVE
    await uow.connections.save(conn)

    use_case = UpdateConnectionUseCase(uow=uow, cipher=cipher)
    cmd = UpdateConnectionCommand(
        connection_id=conn.id,
        tenant_id="ten_01",
        new_name="Acme Renovated",
        updated_raw_credentials={"api_key": "new_secret_key"},
        updated_public_config={"endpoint_url": "https://api.acme.example.com/v2"},
    )
    result = await use_case.execute(cmd)

    assert result.success is True
    assert result.connection is not None
    assert result.connection.name == "Acme Renovated"
    assert result.connection.status == "ACTIVE"
    assert result.connection.public_config == {"endpoint_url": "https://api.acme.example.com/v2"}
    assert uow.committed is True


@pytest.mark.asyncio
async def test_update_connection_use_case_fails_when_deactivated(
    cipher: AesGcmCipher,
) -> None:
    uow = _FakeControlPlaneUoW()
    conn = Connection.create(
        tenant_id="ten_02",
        app_id="acme_app",
        name="Deactivated Acme",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.acme.example.com"},
        encrypted_credentials=b"old_creds",
        endpoint_for_fingerprint="https://api.acme.example.com",
    )
    conn.deactivate()
    await uow.connections.save(conn)

    use_case = UpdateConnectionUseCase(uow=uow, cipher=cipher)
    cmd = UpdateConnectionCommand(
        connection_id=conn.id,
        tenant_id="ten_02",
        new_name="Should Fail Update",
    )
    result = await use_case.execute(cmd)

    assert result.success is False
    assert isinstance(result.error, InvalidConnectionStateError)
    assert uow.committed is False
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_update_connection_use_case_fails_when_not_found(
    cipher: AesGcmCipher,
) -> None:
    uow = _FakeControlPlaneUoW()
    use_case = UpdateConnectionUseCase(uow=uow, cipher=cipher)
    cmd = UpdateConnectionCommand(
        connection_id="ip_conn_missing_999",
        tenant_id="ten_03",
        new_name="Missing Connection",
    )
    result = await use_case.execute(cmd)

    assert result.success is False
    assert isinstance(result.error, ConnectionNotFoundError)
    assert uow.committed is False
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_update_connection_use_case_fails_when_tenant_mismatched(
    cipher: AesGcmCipher,
) -> None:
    uow = _FakeControlPlaneUoW()
    conn = Connection.create(
        tenant_id="ten_correct",
        app_id="acme_app",
        name="Tenant Isolated Acme",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.acme.example.com"},
        encrypted_credentials=b"creds",
        endpoint_for_fingerprint="https://api.acme.example.com",
    )
    await uow.connections.save(conn)

    use_case = UpdateConnectionUseCase(uow=uow, cipher=cipher)
    cmd = UpdateConnectionCommand(
        connection_id=conn.id,
        tenant_id="ten_attacker",
        new_name="Unauthorized Update",
    )
    result = await use_case.execute(cmd)

    assert result.success is False
    assert isinstance(result.error, ConnectionNotFoundError)
    assert uow.committed is False
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_update_connection_preserves_stored_credentials_when_empty_dict_supplied(
    cipher: AesGcmCipher,
) -> None:
    uow = _FakeControlPlaneUoW()
    original_encrypted = cipher.encrypt({"api_key": "persisted_secret_token"})
    conn = Connection.create(
        tenant_id="ten_04",
        app_id="acme_app",
        name="Acme Existing",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.acme.example.com"},
        encrypted_credentials=original_encrypted,
        endpoint_for_fingerprint="https://api.acme.example.com",
    )
    await uow.connections.save(conn)

    use_case = UpdateConnectionUseCase(uow=uow, cipher=cipher)
    result = await use_case.execute(
        UpdateConnectionCommand(
            connection_id=conn.id,
            tenant_id="ten_04",
            new_name="Acme Renamed",
            updated_raw_credentials={},
        )
    )

    assert result.success is True
    saved = await uow.connections.get_by_id(conn.id)
    assert saved is not None
    assert saved.encrypted_credentials == original_encrypted
    assert cipher.decrypt(saved.encrypted_credentials) == {"api_key": "persisted_secret_token"}


@pytest.mark.asyncio
async def test_update_connection_router_rejects_explicit_empty_new_name_despite_fallback_name(
    cipher: AesGcmCipher,
) -> None:
    uow = _FakeControlPlaneUoW()
    conn = Connection.create(
        tenant_id="ten_05",
        app_id="acme_app",
        name="Acme Valid Name",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.acme.example.com"},
        encrypted_credentials=b"creds",
        endpoint_for_fingerprint="https://api.acme.example.com",
    )
    await uow.connections.save(conn)

    identity = IdentityContext(
        subject="usr_admin",
        claims={},
        tenant_id="ten_05",
        authorized_tenants={"ten_05"},
        roles=("TenantAdmin",),
    )
    response = await update_connection(
        tenant_id="ten_05",
        connection_id=conn.id,
        request=UpdateConnectionHttpRequest(new_name="", name="Fallback Name"),
        context=identity,
        ip_cp_uow=uow,
        cipher=cipher,
    )

    assert hasattr(response, "status_code")
    assert response.status_code == 400
    assert b"Connection name cannot be blank." in response.body
    unchanged = await uow.connections.get_by_id(conn.id)
    assert unchanged is not None
    assert unchanged.name == "Acme Valid Name"
