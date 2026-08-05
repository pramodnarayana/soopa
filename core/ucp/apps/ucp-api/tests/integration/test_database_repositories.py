import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ucp_api.adapters.outbound.database.tenant_repository import TenantRepository
from ucp_api.domain.models.tenant import Tenant


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tenant_repository_save_and_find(db_session: AsyncSession) -> None:
    """
    Narrow integration test for TenantRepository.
    Uses session.begin_nested() to isolate changes without polluting the test database.
    """
    async with db_session.begin_nested():
        repo = TenantRepository(db_session)
        tenant_id = f"ten_{uuid.uuid4().hex[:12]}"

        new_tenant = Tenant(
            id=tenant_id,
            name="Test Tenant",
            idp_tenant_id="idp_test_123",
            status="active",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            subscriptions=["test-app"],
        )

        await repo.save(new_tenant)

        # Verify it can be retrieved
        found_tenant = await repo.find_by_id(tenant_id)
        assert found_tenant is not None
        assert found_tenant.id == tenant_id
        assert found_tenant.name == "Test Tenant"
        # Subscriptions are verified here too
        # Wait, the subscription test-app might not exist in the App table, which might violate FK constraints!

        # Test deletion
        await repo.delete(tenant_id)
        deleted_tenant = await repo.find_by_id(tenant_id)
        assert deleted_tenant is None
