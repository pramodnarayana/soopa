import datetime
from typing import Any

import pytest
from fastapi import Request
from identity.domain.identity_context import IdentityContext
from identity.domain.models.authorization import Capability
from seedwork import generate_id, generate_random_hex
from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.domain.models.tenant import LifecycleStatus, Tenant

from unified_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member


@pytest.mark.asyncio
async def test_tenant_auth_mapping_resolves_idp_id(db_session_factory: Any) -> None:
    async with db_session_factory() as session:
        # 1. Insert a fake tenant into the DB so the middleware can map it.
        canonical_id = generate_id("ten")
        idp_id = generate_id("idp")

        repo = TenantRepository(session)
        unique_suffix = generate_random_hex(6)
        tenant = Tenant(
            id=canonical_id,
            name=f"Test Trucking {unique_suffix}",
            slug=f"test-trucking-{unique_suffix}",
            idp_tenant_id=idp_id,
            status=LifecycleStatus.ACTIVE,
            created_at=datetime.datetime.now(datetime.UTC),
            updated_at=datetime.datetime.now(datetime.UTC),
            subscriptions=[],
        )
        await repo.save(tenant)
        await session.flush()

        # 2. We create an IdentityContext exactly like Zitadel gives us natively.
        raw_identity = IdentityContext(
            subject=generate_id("usr"),
            tenant_id=None,
            authorized_tenants={idp_id},
            tenant_mapping={idp_id: canonical_id},
            claims={},
            capabilities={Capability.TENANT_ADMIN.value},
        )

        # 3. Create a fake request and test the guard directly without fakes
        request = Request(scope={"type": "http", "state": {}})
        request.state.identity = raw_identity

        def fake_tenant_repo_factory(session: Any) -> TenantRepository:
            return TenantRepository(session)

        # The guard should successfully authorize and map the IdP ID to the Canonical ID
        identity = await require_tenant_member(
            request=request,
            session=session,
            tenant_repo_factory=fake_tenant_repo_factory,
            tenant_id=idp_id,
        )

        # We only care that it returned the identity and didn't raise 403 Forbidden.
        assert identity.subject == raw_identity.subject
        assert request.state.ucp_tenant_id == canonical_id
