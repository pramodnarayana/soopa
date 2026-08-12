import pytest
from platform_orm.models.identity import Tenant
from platform_orm.models.notifications import NotificationTemplate

from notification.adapters.outbound.postgres_template_repository import (
    PostgresTemplateRepository,
)
from notification.domain.models import Channel


@pytest.mark.asyncio
async def test_get_template(db_session_factory):
    tenant_id = "test-query-tenant"

    # Setup test DB
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name="Test Tenant",
            status="ACTIVE",
        )
        session.add(tenant)

        template = NotificationTemplate(
            id="tpl_123",
            tenant_id=tenant_id,
            name="Invoice Created - Email",
            event_type="invoice.created",
            channel="EMAIL",
            is_active=True,
            subject_template="Subject {{ foo }}",
            body_template="Body {{ foo }}",
        )
        session.add(template)

        template2 = NotificationTemplate(
            id="tpl_456",
            tenant_id=tenant_id,
            name="Invoice Created - In App",
            event_type="invoice.created",
            channel="IN_APP",
            is_active=False,  # INACTIVE!
            subject_template="Ignored",
            body_template="Ignored",
        )
        session.add(template2)

    repo = PostgresTemplateRepository(db_session_factory)

    # Exists and active
    tmpl = await repo.get_template(tenant_id, "invoice.created", Channel.EMAIL)
    assert tmpl is not None
    assert tmpl.id == "tpl_123"
    assert tmpl.subject == "Subject {{ foo }}"

    # Exists but inactive
    tmpl2 = await repo.get_template(tenant_id, "invoice.created", Channel.IN_APP)
    assert tmpl2 is None

    # Does not exist
    tmpl3 = await repo.get_template(tenant_id, "invoice.paid", Channel.EMAIL)
    assert tmpl3 is None
