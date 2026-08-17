from datetime import datetime

import pytest

from ucp.domain.events.tenant_events import TenantDeletedEvent
from ucp.domain.models.tenant import Tenant


def test_tenant_mark_deleted_success() -> None:
    tenant = Tenant.create(id="ten_123", name="Test", slug="test", idp_tenant_id="org_123")
    assert tenant.deleted_at is None

    tenant.mark_deleted()

    assert tenant.deleted_at is not None
    assert isinstance(tenant.deleted_at, datetime)
    assert len(tenant.domain_events) == 2
    assert isinstance(tenant.domain_events[-1], TenantDeletedEvent)
    assert tenant.domain_events[-1].event_name == "TenantDeleted"


def test_tenant_mark_deleted_already_deleted() -> None:
    tenant = Tenant.create(id="ten_123", name="Test", slug="test", idp_tenant_id="org_123")
    tenant.mark_deleted()

    with pytest.raises(ValueError, match="already been deleted"):
        tenant.mark_deleted()
