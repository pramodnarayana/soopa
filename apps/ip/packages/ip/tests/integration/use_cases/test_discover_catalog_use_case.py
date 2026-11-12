"""Narrow integration tests for DiscoverCatalogUseCase using real PostgreSQL SAVEPOINTs and local HTTP server."""

from __future__ import annotations

import pytest
from database.types import GlobalSession
from identity.domain.constants import IdentityIdPrefix
from ip.engine.adapters.outbound.auth.resolver import AuthStrategyResolver
from ip.engine.adapters.outbound.connectors.generic_http_connector import (
    GenericHttpConnector,
)
from ip.engine.application.use_cases.connections.create_connection_use_case import (
    CreateConnectionCommand,
    CreateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.discover_catalog_use_case import (
    DiscoverCatalogUseCase,
)
from ip.engine.bootstrap.container import create_ip_control_plane_uow
from ip.engine.domain.exceptions import IpErrorCode
from pytest_httpserver import HTTPServer
from security.adapters.ciphers.aes_gcm_cipher import AesGcmCipher
from seedwork import generate_id

pytestmark = pytest.mark.integration


@pytest.fixture
def cipher() -> AesGcmCipher:
    key = AesGcmCipher.generate_key()
    return AesGcmCipher(key)


@pytest.mark.asyncio
async def test_discover_catalog_use_case(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
        headers={"X-API-Key": "valid_token"},
    ).respond_with_json(
        {
            "streams": [
                {
                    "name": "records_alpha",
                    "fields": [{"name": "id", "data_type": "string", "nullable": False}],
                    "primary_key": ["id"],
                    "supported_sync_modes": ["FULL_REFRESH", "INCREMENTAL"],
                },
                {
                    "name": "interval_events",
                    "fields": [{"name": "record_id", "data_type": "string", "nullable": False}],
                    "primary_key": ["record_id"],
                    "supported_sync_modes": ["FULL_REFRESH", "INCREMENTAL"],
                },
                {
                    "name": "parent_entities",
                    "fields": [{"name": "id", "data_type": "string", "nullable": False}],
                    "primary_key": ["id"],
                    "supported_sync_modes": ["FULL_REFRESH"],
                },
            ]
        },
        status=200,
    )

    connector = GenericHttpConnector(
        app_id="acme_source",
        auth_resolver=AuthStrategyResolver(),
        allow_private_ips=True,
    )
    uow = create_ip_control_plane_uow(global_session)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    conn_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="acme_source",
            name="Acme Source",
            auth_type="API_KEY",
            public_config={"endpoint_url": httpserver.url_for("")},
            raw_credentials={"api_key": "valid_token"},
            endpoint_for_fingerprint=httpserver.url_for(""),
        )
    )
    assert conn_res.success is True
    assert conn_res.connection is not None
    conn_dto = conn_res.connection

    discover_uc = DiscoverCatalogUseCase(
        uow=uow,
        cipher=cipher,
        connectors={connector.app_id: connector},
    )

    result = await discover_uc.execute(conn_dto.id, tenant_id=tenant_id)
    assert result.is_ok and result.value is not None
    catalog_dto = result.value
    assert catalog_dto.success is True
    assert catalog_dto.connection_id == conn_dto.id
    assert len(catalog_dto.catalog_hash) == 64
    assert len(catalog_dto.streams) == 3

    # Stateless discovery MUST NOT auto-subscribe entities in Control Plane
    async with uow:
        subscribed_entities = await uow.entities.list_by_connection(tenant_id, conn_dto.id)
    assert len(subscribed_entities) == 0


@pytest.mark.asyncio
async def test_discover_catalog_skips_unsupported_sync_modes(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request(
        "/api/v1/schema/streams",
        method="GET",
        headers={"X-API-Key": "valid_token"},
    ).respond_with_json(
        {
            "streams": [
                {
                    "name": "supported_stream",
                    "fields": [{"name": "id", "data_type": "string", "nullable": False}],
                    "primary_key": ["id"],
                    "supported_sync_modes": ["INCREMENTAL"],
                },
                {
                    "name": "unsupported_stream",
                    "fields": [{"name": "id", "data_type": "string", "nullable": False}],
                    "primary_key": ["id"],
                    "supported_sync_modes": ["COMPLETELY_INVALID_MODE"],
                },
            ]
        },
        status=200,
    )

    connector = GenericHttpConnector(
        app_id="acme_source",
        auth_resolver=AuthStrategyResolver(),
        allow_private_ips=True,
    )
    uow = create_ip_control_plane_uow(global_session)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)

    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    conn_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="acme_source",
            name="Acme Custom Schema",
            auth_type="API_KEY",
            public_config={"endpoint_url": httpserver.url_for("")},
            raw_credentials={"api_key": "valid_token"},
            endpoint_for_fingerprint=httpserver.url_for(""),
        )
    )
    assert conn_res.success is True
    assert conn_res.connection is not None
    conn_dto = conn_res.connection

    discover_uc = DiscoverCatalogUseCase(
        uow=uow,
        cipher=cipher,
        connectors={connector.app_id: connector},
    )

    result = await discover_uc.execute(conn_dto.id, tenant_id=tenant_id)
    assert result.is_ok and result.value is not None
    catalog_dto = result.value
    assert catalog_dto.success is True
    assert len(catalog_dto.streams) == 1
    assert catalog_dto.streams[0].name == "supported_stream"
    assert list(catalog_dto.streams[0].supported_sync_modes) == ["INCREMENTAL"]


@pytest.mark.asyncio
async def test_discover_catalog_connection_not_found_returns_failure(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    discover_uc = DiscoverCatalogUseCase(
        uow=uow,
        cipher=cipher,
        connectors={},
    )
    result = await discover_uc.execute("non_existent_id", tenant_id="ten_nonexistent")
    assert result.is_err
    assert result.error is not None
    assert result.error.code == IpErrorCode.CONNECTION_NOT_FOUND


@pytest.mark.asyncio
async def test_discover_catalog_connector_not_found_returns_failure(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    conn_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="unregistered_app",
            name="Unregistered",
            auth_type="API_KEY",
            public_config={},
            raw_credentials={"api_key": "tok"},
            endpoint_for_fingerprint="https://api.example.com",
        )
    )
    assert conn_res.success is True
    assert conn_res.connection is not None

    discover_uc = DiscoverCatalogUseCase(
        uow=uow,
        cipher=cipher,
        connectors={},
    )
    result = await discover_uc.execute(conn_res.connection.id, tenant_id=tenant_id)
    assert result.is_err
    assert result.error is not None
    assert result.error.code == IpErrorCode.CONNECTOR_NOT_FOUND


@pytest.mark.asyncio
async def test_discover_catalog_pending_auth_api_key_returns_pending_auth_error(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    connector = GenericHttpConnector(
        app_id="acme_source",
        auth_resolver=AuthStrategyResolver(),
        allow_private_ips=True,
    )
    uow = create_ip_control_plane_uow(global_session)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    conn_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="acme_source",
            name="Pending Auth Conn",
            auth_type="API_KEY",
            public_config={"endpoint_url": "https://api.example.com"},
            raw_credentials={},
            endpoint_for_fingerprint="https://api.example.com",
        )
    )
    assert conn_res.success is True
    assert conn_res.connection is not None

    discover_uc = DiscoverCatalogUseCase(
        uow=uow,
        cipher=cipher,
        connectors={connector.app_id: connector},
    )
    result = await discover_uc.execute(conn_res.connection.id, tenant_id=tenant_id)
    assert result.is_err
    assert result.error is not None
    assert result.error.code == IpErrorCode.CONNECTION_PENDING_AUTH


@pytest.mark.asyncio
async def test_discover_catalog_deactivated_connection_returns_failure(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    conn_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="acme_source",
            name="Deactivated Conn",
            auth_type="API_KEY",
            public_config={},
            raw_credentials={},
            endpoint_for_fingerprint="https://api.example.com",
        )
    )
    assert conn_res.success is True
    assert conn_res.connection is not None

    async with uow:
        conn = await uow.connections.get_by_id(conn_res.connection.id)
        assert conn is not None
        conn.deactivate()
        await uow.connections.save(conn)
        await uow.commit()

    discover_uc = DiscoverCatalogUseCase(
        uow=uow,
        cipher=cipher,
        connectors={},
    )
    result = await discover_uc.execute(conn_res.connection.id, tenant_id=tenant_id)
    assert result.is_err
    assert result.error is not None
    assert result.error.code == IpErrorCode.CONNECTION_DEACTIVATED


@pytest.mark.asyncio
async def test_discover_catalog_mismatched_tenant_id_returns_not_found(
    global_session: GlobalSession,
    cipher: AesGcmCipher,
) -> None:
    uow = create_ip_control_plane_uow(global_session)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    create_uc = CreateConnectionUseCase(uow=uow, cipher=cipher)
    conn_res = await create_uc.execute(
        CreateConnectionCommand(
            tenant_id=tenant_id,
            app_id="acme_source",
            name="Tenant Isolation Test",
            auth_type="API_KEY",
            public_config={},
            raw_credentials={},
            endpoint_for_fingerprint="https://api.example.com",
        )
    )
    assert conn_res.success is True
    assert conn_res.connection is not None

    discover_uc = DiscoverCatalogUseCase(
        uow=uow,
        cipher=cipher,
        connectors={},
    )
    wrong_tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    result = await discover_uc.execute(conn_res.connection.id, tenant_id=wrong_tenant_id)
    assert result.is_err
    assert result.error is not None
    assert result.error.code == IpErrorCode.CONNECTION_NOT_FOUND
