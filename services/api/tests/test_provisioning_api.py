import uuid
from typing import Any
from uuid import UUID

import pytest
from api.core.provisioning import ProvisioningService
from api.domain.models import CreateTradingPartnerRequest
from api.main import app
from api.ports.repository import ControlPlaneRepositoryPort
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


class InMemoryControlPlaneRepository(ControlPlaneRepositoryPort):
    def __init__(self):
        self.partners = {}
        self.connections = {}
        self.outbox = {}

    async def create_trading_partner(
        self, tenant_id: int, partner_name: str, as2_id: str | None, direction: str
    ) -> UUID:
        partner_id = uuid.uuid4()
        self.partners[partner_id] = {
            "tenant_id": tenant_id,
            "partner_name": partner_name,
            "as2_id": as2_id,
            "direction": direction,
        }
        return partner_id

    async def create_connection(
        self, trading_partner_id: UUID, tenant_id: int, request: CreateTradingPartnerRequest
    ) -> UUID:
        directions = ["INBOUND", "OUTBOUND"] if request.direction == "BOTH" else [request.direction]
        first_conn_id = None
        for dir_val in directions:
            conn_id = uuid.uuid4()
            if not first_conn_id:
                first_conn_id = conn_id
            self.connections[conn_id] = {
                "trading_partner_id": trading_partner_id,
                "tenant_id": tenant_id,
                "connection_type": request.connection_type,
                "host": request.host,
                "port": request.port,
                "direction": dir_val,
                "credentials_vault_ref": request.credentials_vault_ref,
            }
        return first_conn_id

    async def create_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> UUID:
        event_id = uuid.uuid4()
        self.outbox[event_id] = {
            "tenant_id": tenant_id,
            "event_type": event_type,
            "payload": payload,
        }
        return event_id


async def test_provisioning_service_zero_mocks():
    """
    Tests pure domain logic using an in-memory repository with zero mocks.
    """
    repo = InMemoryControlPlaneRepository()
    service = ProvisioningService(repo)

    request = CreateTradingPartnerRequest(
        partner_name="Acme Corp",
        as2_id="ACME",
        direction="BOTH",
        connection_type="AS2",
        host="as2.acme.com",
        port=8080,
        credentials_vault_ref="vault://secret1",
    )

    response = await service.provision_trading_partner(99, request)

    assert response.status == "PROVISIONING"
    assert response.tenant_id == 99

    # Assert DB state
    assert len(repo.partners) == 1
    assert len(repo.connections) == 2  # BOTH direction creates 2 connections
    assert len(repo.outbox) == 1

    partner_id = response.trading_partner_id
    assert repo.partners[partner_id]["partner_name"] == "Acme Corp"

    conn = list(repo.connections.values())[0]
    assert conn["trading_partner_id"] == partner_id
    assert conn["host"] == "as2.acme.com"

    outbox_event = list(repo.outbox.values())[0]
    assert outbox_event["event_type"] == "TRADING_PARTNER_PROVISION"
    assert outbox_event["payload"]["trading_partner_id"] == str(partner_id)
    assert outbox_event["payload"]["tenant_id"] == 99


async def test_api_endpoint_create_trading_partner() -> None:
    """
    Tests the FastAPI endpoint utilizing the SqlAlchemy adapter directly.
    db_session is an async session that will be rolled back.
    """
    # Override dependencies
    from unittest.mock import AsyncMock, MagicMock

    from api.dependencies import get_global_session
    from identity.dependencies import get_current_tenant_id

    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    async def get_mock_session():
        yield mock_session

    app.dependency_overrides[get_global_session] = get_mock_session
    app.dependency_overrides[get_current_tenant_id] = lambda: 99

    payload = {
        "partner_name": "Acme API Corp",
        "as2_id": "ACME_API",
        "direction": "INBOUND",
        "connection_type": "SFTP",
        "host": "sftp.acme.com",
        "port": 22,
        "credentials_vault_ref": "vault://sftp",
    }

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/trading-partners", json=payload)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "PROVISIONING"
        assert data["tenant_id"] == 99
        assert "trading_partner_id" in data
    finally:
        app.dependency_overrides.clear()
