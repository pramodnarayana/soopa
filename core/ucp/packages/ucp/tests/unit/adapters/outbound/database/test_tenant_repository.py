from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from database.models.identity import Tenant as DbTenant
from sqlalchemy import CheckConstraint

from ucp.adapters.outbound.database.tenant_repository import TenantRepository
from ucp.domain.constants import LifecycleStatus


def test_tenant_status_is_constrained_to_lifecycle_values() -> None:
    status_constraint = next(
        constraint
        for constraint in DbTenant.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == "ck_tenants_status"
    )

    assert str(status_constraint.sqltext) == "status IN ('active', 'inactive')"


@pytest.mark.asyncio
async def test_find_all_maps_subscription_status_to_lifecycle_status() -> None:
    row = SimpleNamespace(
        id="ten_123",
        name="Tenant",
        slug="tenant",
        idp_tenant_id=None,
        status="active",
        created_at=datetime.now(UTC).replace(tzinfo=None),
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    tenants_result = MagicMock()
    tenants_result.scalars.return_value.all.return_value = [row]
    subscriptions_result = MagicMock()
    subscriptions_result.__iter__.return_value = iter([("ten_123", "edi", "active")])
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[tenants_result, subscriptions_result])

    tenants = await TenantRepository(session).find_all()

    assert tenants[0].subscriptions[0].status is LifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_load_subscription_ids_maps_status_to_lifecycle_status() -> None:
    result = MagicMock()
    result.all.return_value = [("edi", "inactive")]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    subscriptions = await TenantRepository(session)._load_subscription_ids("ten_123")

    assert subscriptions[0].status is LifecycleStatus.INACTIVE
