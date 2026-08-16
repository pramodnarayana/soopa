import pytest

pytestmark = pytest.mark.integration
from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_tenant_auth_bug(client: AsyncClient, db_session: Any) -> None:
    # This test hits the tenant GET endpoint using the IdP Tenant ID.
    # We must mock the authenticate_bearer_token to return an IdentityContext
    # simulating what Zitadel gives us natively (IdP ID in authorized_tenants).

    # 1. Insert a mock tenant into the DB so the middleware can map it.
    import datetime
    import uuid

    from ucp.adapters.outbound.database.tenant_repository import TenantRepository
    from ucp.domain.models.tenant import Tenant

    canonical_id = f"ten_{uuid.uuid4().hex[:20]}"
    idp_id = "385223051081416707"

    repo = TenantRepository(db_session)
    tenant = Tenant(
        id=canonical_id,
        name="Test Trucking",
        idp_tenant_id=idp_id,
        status="active",
        created_at=datetime.datetime.now(datetime.UTC),
        updated_at=datetime.datetime.now(datetime.UTC),
        subscriptions=[],
    )
    await repo.save(tenant)
    await db_session.commit()

    # 2. Override the token verifier in the app to return a fake identity
    from identity.domain.identity_context import IdentityContext
    from ucp.main import app  # type: ignore

    # Remove the generic guard overrides so the REAL auth logic executes!
    from ucp.adapters.inbound.http.guards import tenant_auth_guard
    from ucp.domain.models.authorization import Capability

    if tenant_auth_guard.require_tenant_member in app.dependency_overrides:
        del app.dependency_overrides[tenant_auth_guard.require_tenant_member]

    # We create an IdentityContext exactly like Zitadel gives us.
    raw_identity = IdentityContext(
        subject="385223078428278787",
        tenant_id=None,
        authorized_tenants={idp_id},
        claims={},
        capabilities={Capability.TENANT_ADMIN.value},
    )

    # We override the authenticate_bearer_token function that the middleware calls
    from unittest.mock import patch

    with patch(
        "ucp.adapters.inbound.http.middleware.authentication.authenticate_bearer_token",
        autospec=True,
    ) as mock_auth:
        mock_auth.return_value = raw_identity

        # 3. Hit the endpoint using the IdP ID
        response = await client.get(
            f"/api/v1/tenants/{idp_id}", headers={"Authorization": "Bearer mock"}
        )

        # It SHOULD be 200 OK!
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}. Body: {response.json()}"
        )
