from typing import Any

from edi.dependencies.auth import (
    get_current_tenant_id,
    get_current_user_profile,
    get_platform_user_profile,
    require_platform_admin,
)
from edi.dependencies.database import get_control_plane_uow
from edi.dependencies.services import get_as2_tester, get_secret_store

"""
Tests for the AS2 Partnership connection test endpoint.

POST /api/v1/platform/trading-partners/as2/partnerships/{id}/test

All infrastructure is injected via FakeControlPlaneUnitOfWork, a fixture-controlled FakeAS2Tester,
and FakeVault — zero real network connections or Vault required.
"""

import uuid
from collections.abc import Callable

import pytest
from api_fakes import FakeControlPlaneUnitOfWork
from fastapi.testclient import TestClient
from identity.domain.identity_context import PLATFORM_TENANT_ID

from edi.module import create_edi_app

app = create_edi_app()

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAS2Tester:
    """
    Controllable fake for AS2TesterPort.
    """

    def __init__(self, *, transport_ok: bool, result: str) -> None:
        self._transport_ok = transport_ok
        self._result = result

    async def test_connection(self, **kwargs) -> tuple[bool, str | None, str | None, str | None]:
        return self._transport_ok, self._result, "mock-sent-payload", "mock-raw-mdn"


class FakeVault:
    async def retrieve_secret(self, vault_ref: str) -> bytes:
        return b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----"

    async def retrieve_private_key(self, vault_ref: str) -> bytes:
        return await self.retrieve_secret(vault_ref)

    async def store_private_key(self, private_key_pem: bytes, category: Any = None) -> str:
        return "vault_ref_123"

    async def delete_secret(self, vault_ref: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_uow() -> FakeControlPlaneUnitOfWork:
    return FakeControlPlaneUnitOfWork()


@pytest.fixture
def client_factory(fake_uow: FakeControlPlaneUnitOfWork) -> Callable[..., TestClient]:
    """
    Factory fixture that creates a TestClient with all dependency overrides
    registered BEFORE the TestClient context is entered. This ensures no
    global state mutation occurs inside test bodies.

    Usage:
        def test_something(client_factory, fake_uow):
            client = client_factory(transport_ok=True, result="processed")
    """
    active_clients: list[TestClient] = []

    def _make(*, transport_ok: bool = True, result: str = "processed") -> TestClient:
        fake_tester = FakeAS2Tester(transport_ok=transport_ok, result=result)

        app.dependency_overrides[get_control_plane_uow] = lambda: fake_uow
        app.dependency_overrides[get_current_tenant_id] = lambda: PLATFORM_TENANT_ID
        app.dependency_overrides[require_platform_admin] = lambda: PLATFORM_TENANT_ID
        app.dependency_overrides[get_platform_user_profile] = lambda: {
            "sub": "test",
            "tenant_id": "0",
            "permissions": ["platform:admin"],
        }
        app.dependency_overrides[get_current_user_profile] = lambda: {
            "sub": "test",
            "tenant_id": "1",
            "permissions": ["*"],
        }
        app.dependency_overrides[get_secret_store] = lambda: FakeVault()
        app.dependency_overrides[get_as2_tester] = lambda: fake_tester

        ctx = TestClient(app)
        ctx.__enter__()
        active_clients.append(ctx)
        return ctx

    yield _make

    for ctx in active_clients:
        ctx.__exit__(None, None, None)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_partnership(
    client: TestClient, fake_uow: FakeControlPlaneUnitOfWork
) -> tuple[str, str, str]:
    """
    Creates local partner → remote partner → partnership via the real API.
    Returns (local_id, remote_id, partnership_id).
    """
    local_resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={
            "name": "Our Company",
            "as2_id": "OURCO",
            "is_local": True,
            "url": None,
            "public_cert_pem": None,
            "public_cert_vault_ref": None,
            "private_key_vault_ref": None,
        },
    )
    assert local_resp.status_code == 201
    local_id = local_resp.json()["id"]

    remote_resp = client.post(
        "/api/v1/platform/trading-partners/as2/trading-partners",
        json={
            "name": "Mendelson",
            "as2_id": "MENDELSON",
            "is_local": False,
            "url": "http://localhost:8080/as2/HttpReceiver",
            "public_cert_pem": None,
            "public_cert_vault_ref": None,
            "private_key_vault_ref": None,
        },
    )
    assert remote_resp.status_code == 201
    remote_id = remote_resp.json()["id"]

    partnership_resp = client.post(
        "/api/v1/platform/trading-partners/as2/partnerships",
        json={
            "name": "OURCO <> Mendelson",
            "local_partner_id": local_id,
            "remote_partner_id": remote_id,
            "mdn_type": "SYNC",
            "encryption_algorithm": "AES256",
            "signature_algorithm": "SHA256",
        },
    )
    assert partnership_resp.status_code == 201
    partnership_id = partnership_resp.json()["id"]
    return local_id, remote_id, partnership_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_test_as2_partnership_success(client_factory, fake_uow):
    """
    Remote partner returns a 'processed' MDN disposition.
    The endpoint must parse the business rule and return success=True.
    """
    # Adapter returns raw full disposition; router applies RFC 4130 business rule.
    client = client_factory(
        transport_ok=True,
        result="automatic-action/MDN-sent-automatically; processed",
    )
    _, _, partnership_id = _create_partnership(client, fake_uow)

    response = client.post(
        f"/api/v1/platform/trading-partners/as2/partnerships/{partnership_id}/test"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["mdn_disposition"] == "processed"
    assert data["reason"] is None


def test_test_as2_partnership_failure_mdn_auth(client_factory, fake_uow):
    """
    Remote partner returns an 'authentication-failed' MDN.
    The endpoint must return success=False with the disposition as the reason.
    """
    client = client_factory(
        transport_ok=True,
        result="automatic-action/MDN-sent-automatically; processed/error: authentication-failed",
    )
    _, _, partnership_id = _create_partnership(client, fake_uow)

    response = client.post(
        f"/api/v1/platform/trading-partners/as2/partnerships/{partnership_id}/test"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "authentication-failed" in data["reason"]


def test_test_as2_partnership_connection_refused(client_factory, fake_uow):
    """
    Transport failure (no HTTP response received).
    The endpoint must return success=False immediately without applying MDN rules.
    """
    client = client_factory(
        transport_ok=False,
        result="Connection refused: [Errno 111] Connection refused",
    )
    _, _, partnership_id = _create_partnership(client, fake_uow)

    response = client.post(
        f"/api/v1/platform/trading-partners/as2/partnerships/{partnership_id}/test"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Connection refused" in data["reason"]


def test_test_as2_partnership_not_found(client_factory):
    """Returns 404 when the partnership ID does not exist in the database."""
    client = client_factory()

    response = client.post(
        f"/api/v1/platform/trading-partners/as2/partnerships/{uuid.uuid4()!s}/test"
    )

    assert response.status_code == 404
