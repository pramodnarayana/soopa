"""Unit tests for Connection Application Use Cases using pure in-memory test fakes and narrow HTTP test harness."""

from collections.abc import Sequence

import pytest
from ip.adapters.outbound.connectors.itron_mdm_connector import ItronMdmConnector
from ip.application.connections.check_connection_use_case import (
    CheckConnectionCommand,
    CheckConnectionUseCase,
)
from ip.application.connections.create_connection_use_case import (
    CreateConnectionCommand,
    CreateConnectionUseCase,
)
from ip.application.connections.deactivate_connection_use_case import (
    DeactivateConnectionCommand,
    DeactivateConnectionUseCase,
)
from ip.application.connections.discover_catalog_use_case import DiscoverCatalogUseCase
from ip.application.connections.relink_connection_use_case import (
    RelinkConnectionCommand,
    RelinkConnectionUseCase,
)
from ip.domain.exceptions import (
    DuplicateConnectionFingerprintException,
)
from ip.domain.models.catalog import ConnectionCatalog
from ip.domain.models.connection import Connection, ConnectionStatus
from ip.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from pytest_httpserver import HTTPServer
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher


class InMemoryConnectionRepository(ConnectionRepositoryPort):
    """Pure in-memory repository fake for testing without database dependencies."""

    def __init__(self) -> None:
        self.connections: dict[str, Connection] = {}

    async def save(self, connection: Connection) -> None:
        self.connections[connection.id] = connection
        connection.clear_domain_events()

    async def get_by_id(self, connection_id: str) -> Connection | None:
        return self.connections.get(connection_id)

    async def get_by_fingerprint(
        self,
        tenant_id: str,
        fingerprint: str,
    ) -> Connection | None:
        for c in self.connections.values():
            if c.tenant_id == tenant_id and c.connection_fingerprint == fingerprint:
                return c
        return None

    async def list_by_tenant(
        self,
        tenant_id: str,
        status: ConnectionStatus | None = None,
    ) -> Sequence[Connection]:
        res = [c for c in self.connections.values() if c.tenant_id == tenant_id]
        if status is not None:
            res = [c for c in res if c.status == status]
        return res


class InMemoryCatalogRepository(CatalogRepositoryPort):
    """Pure in-memory catalog repository fake for testing."""

    def __init__(self) -> None:
        self.catalogs: dict[str, list[ConnectionCatalog]] = {}

    async def save(self, catalog: ConnectionCatalog) -> None:
        if catalog.connection_id not in self.catalogs:
            self.catalogs[catalog.connection_id] = []
        self.catalogs[catalog.connection_id].append(catalog)

    async def get_active_by_connection_id(
        self,
        connection_id: str,
    ) -> ConnectionCatalog | None:
        history = self.catalogs.get(connection_id, [])
        active = [c for c in history if c.is_active]
        return active[-1] if active else None

    async def get_by_version(
        self,
        connection_id: str,
        version: int,
    ) -> ConnectionCatalog | None:
        for c in self.catalogs.get(connection_id, []):
            if c.catalog_version == version:
                return c
        return None


@pytest.fixture
def cipher() -> AesGcmCipher:
    key = AesGcmCipher.generate_key()
    return AesGcmCipher(key)


@pytest.mark.asyncio
async def test_create_connection_use_case(cipher: AesGcmCipher) -> None:
    repo = InMemoryConnectionRepository()
    use_case = CreateConnectionUseCase(connection_repo=repo, cipher=cipher)

    cmd = CreateConnectionCommand(
        tenant_id="ten_energy_1",
        app_id="itron_mdm",
        name="Utility Itron Head-End",
        auth_type="API_KEY",
        public_config={"endpoint_url": "https://ami.gridpower.com"},
        raw_credentials={"api_key": "sec_top_secret"},
        endpoint_for_fingerprint="https://ami.gridpower.com",
    )

    dto = await use_case.execute(cmd)

    assert dto.id.startswith("ip_conn_")
    assert dto.tenant_id == "ten_energy_1"
    assert dto.name == "Utility Itron Head-End"
    assert dto.status == "PENDING_AUTH"

    # Verify credentials stored in repository are encrypted
    stored = await repo.get_by_id(dto.id)
    assert stored is not None
    assert stored.encrypted_credentials is not None
    assert cipher.decrypt(stored.encrypted_credentials) == {"api_key": "sec_top_secret"}


@pytest.mark.asyncio
async def test_create_duplicate_active_connection_rejected(cipher: AesGcmCipher) -> None:
    repo = InMemoryConnectionRepository()
    use_case = CreateConnectionUseCase(connection_repo=repo, cipher=cipher)

    cmd = CreateConnectionCommand(
        tenant_id="ten_energy_1",
        app_id="itron_mdm",
        name="Utility Itron",
        auth_type="API_KEY",
        public_config={"endpoint_url": "https://ami.gridpower.com"},
        raw_credentials={"api_key": "sec_1"},
        endpoint_for_fingerprint="https://ami.gridpower.com",
    )

    dto = await use_case.execute(cmd)
    conn = await repo.get_by_id(dto.id)
    assert conn is not None
    conn.activate()  # Mark connection active

    with pytest.raises(DuplicateConnectionFingerprintException):
        await use_case.execute(cmd)


@pytest.mark.asyncio
async def test_check_connection_use_case(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/health",
        method="GET",
        headers={"X-API-Key": "valid_token"},
    ).respond_with_json({"status": "ok", "system": "Itron Head-End"})

    connector = ItronMdmConnector()
    use_case = CheckConnectionUseCase(connectors={connector.app_id: connector})

    cmd = CheckConnectionCommand(
        app_id="itron_mdm",
        auth_type="API_KEY",
        public_config={"endpoint_url": httpserver.url_for("")},
        raw_credentials={"api_key": "valid_token"},
    )

    result = await use_case.execute(cmd)
    assert result.success is True
    assert result.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_check_connection_unknown_connector_returns_structured_failure() -> None:
    use_case = CheckConnectionUseCase(connectors={})
    cmd = CheckConnectionCommand(
        app_id="non_existent_app",
        auth_type="API_KEY",
        public_config={},
        raw_credentials={},
    )
    result = await use_case.execute(cmd)
    assert result.success is False
    assert result.status == "FAILED"
    assert result.error_code == "CONNECTOR_NOT_FOUND"
    assert "non_existent_app" in result.message


@pytest.mark.asyncio
async def test_discover_catalog_use_case(cipher: AesGcmCipher, httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
        headers={"X-API-Key": "valid_token"},
    ).respond_with_data("Not found", status=404)

    connector = ItronMdmConnector()
    conn_repo = InMemoryConnectionRepository()
    cat_repo = InMemoryCatalogRepository()

    create_uc = CreateConnectionUseCase(connection_repo=conn_repo, cipher=cipher)
    conn_dto = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id="ten_1",
            app_id="itron_mdm",
            name="Itron",
            auth_type="API_KEY",
            public_config={"endpoint_url": httpserver.url_for("")},
            raw_credentials={"api_key": "valid_token"},
            endpoint_for_fingerprint=httpserver.url_for(""),
        )
    )

    discover_uc = DiscoverCatalogUseCase(
        connection_repo=conn_repo,
        catalog_repo=cat_repo,
        cipher=cipher,
        connectors={connector.app_id: connector},
    )

    catalog_dto = await discover_uc.execute(conn_dto.id)
    assert catalog_dto.connection_id == conn_dto.id
    assert len(catalog_dto.streams) == 3

    # Check persistence
    persisted_catalog = await cat_repo.get_active_by_connection_id(conn_dto.id)
    assert persisted_catalog is not None
    assert persisted_catalog.catalog_version == 1
    assert persisted_catalog.catalog_hash == catalog_dto.catalog_hash


@pytest.mark.asyncio
async def test_deactivate_and_relink_lifecycle(cipher: AesGcmCipher) -> None:
    conn_repo = InMemoryConnectionRepository()
    create_uc = CreateConnectionUseCase(connection_repo=conn_repo, cipher=cipher)

    dto = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id="ten_1",
            app_id="itron_mdm",
            name="Itron",
            auth_type="API_KEY",
            public_config={"endpoint_url": "https://ami.gridpower.com"},
            raw_credentials={"api_key": "valid_token"},
            endpoint_for_fingerprint="https://ami.gridpower.com",
        )
    )

    # 1. Deactivate
    deact_uc = DeactivateConnectionUseCase(connection_repo=conn_repo)
    deact_dto = await deact_uc.execute(
        DeactivateConnectionCommand(connection_id=dto.id, tenant_id="ten_1")
    )
    assert deact_dto.status == "DEACTIVATED"
    assert deact_dto.deactivated_at is not None

    # 2. Relink
    relink_uc = RelinkConnectionUseCase(connection_repo=conn_repo, cipher=cipher)
    relink_dto = await relink_uc.execute(
        RelinkConnectionCommand(
            connection_id=dto.id,
            tenant_id="ten_1",
            new_name="Itron Resurrected",
            updated_raw_credentials={"api_key": "new_refreshed_key"},
        )
    )

    assert relink_dto.status == "ACTIVE"
    assert relink_dto.name == "Itron Resurrected"
    assert relink_dto.deactivated_at is None

    # Verify updated credentials in repo
    updated_conn = await conn_repo.get_by_id(dto.id)
    assert updated_conn is not None
    assert updated_conn.encrypted_credentials is not None
    assert cipher.decrypt(updated_conn.encrypted_credentials) == {"api_key": "new_refreshed_key"}
