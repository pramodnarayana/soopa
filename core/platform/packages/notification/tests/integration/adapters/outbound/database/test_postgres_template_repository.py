import pytest
from database.models.identity import Tenant
from database.models.notifications import NotificationTemplate
from seedwork import generate_id, generate_random_hex
from ucp.domain.constants import LifecycleStatus

from notification.adapters.outbound.database.postgres_template_repository import (
    SqlAlchemyTemplateRepository,
)
from notification.domain.models import Channel


@pytest.mark.asyncio
async def test_get_template(db_session_factory):
    tenant_id = f"test-query-tenant-{generate_random_hex(6)}"

    # Setup test DB
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {generate_random_hex(6)}",
            slug=tenant_id,
            status=LifecycleStatus.ACTIVE,
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

    async with db_session_factory() as session:
        repo = SqlAlchemyTemplateRepository(session)

        # Exists and active
        tmpl = await repo.get_template(tenant_id, "invoice.created", Channel.EMAIL)
        assert tmpl is not None
        assert tmpl.id == "tpl_123"
        assert tmpl.subject == "Subject {{ foo }}"

        # Exists but inactive
        tmpl2 = await repo.get_template(tenant_id, "invoice.created", Channel.IN_APP)
        assert tmpl2 is None

        # Does not exist
        tmpl3 = await repo.get_template(tenant_id, "nonexistent", Channel.EMAIL)
        assert tmpl3 is None


@pytest.mark.asyncio
async def test_template_crud_operations(db_session_factory):
    tenant_id = f"test-crud-tenant-{generate_random_hex(6)}"

    # Setup test DB
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {generate_random_hex(6)}",
            slug=tenant_id,
            status=LifecycleStatus.ACTIVE,
        )
        session.add(tenant)

    async with db_session_factory() as session:
        repo = SqlAlchemyTemplateRepository(session)

        # 1. UPSERT (Insert)
        tmpl = await repo.upsert_template(
            tenant_id=tenant_id,
            name="Welcome Email",
            event_type="user.welcome",
            channel="EMAIL",
            subject_template="Welcome {{ name }}",
            body_template="Hello {{ name }}",
            is_active=True,
        )
        await session.commit()
        assert tmpl.name == "Welcome Email"
        assert tmpl.event_type == "user.welcome"
        assert tmpl.is_active is True

        # 2. LIST
        tmpls = await repo.list_templates(tenant_id)
        assert len(tmpls) == 1
        assert tmpls[0].id == tmpl.id

        # 3. UPSERT (Update)
        tmpl_updated = await repo.upsert_template(
            tenant_id=tenant_id,
            name="Welcome Email Updated",
            event_type="user.welcome",
            channel="EMAIL",
            subject_template="Welcome {{ name }}!",
            body_template="Hello {{ name }}!",
            is_active=False,
        )
        await session.commit()
        assert tmpl_updated.id == tmpl.id
        assert tmpl_updated.name == "Welcome Email Updated"
        assert tmpl_updated.is_active is False

        # 4. DELETE
        deleted = await repo.delete_template(tenant_id, tmpl.id)
        assert deleted is True

        # Attempt delete again
        deleted2 = await repo.delete_template(tenant_id, tmpl.id)
        assert deleted2 is False

        await session.commit()

        # Verify List is empty
        tmpls_after = await repo.list_templates(tenant_id)
        assert len(tmpls_after) == 0


@pytest.mark.asyncio
async def test_get_template_fallback_to_platform(db_session_factory):
    tenant_id = f"test-plat-tenant-{generate_random_hex(6)}"
    event_type = f"system.alert.{generate_random_hex(6)}"
    from notification.domain.models import PLATFORM_TENANT_ID

    # Setup test DB
    async with db_session_factory() as session, session.begin():
        tenant = Tenant(
            id=tenant_id,
            name=f"Test Tenant {generate_random_hex(6)}",
            slug=tenant_id,
            status=LifecycleStatus.ACTIVE,
        )
        session.add(tenant)

        platform_tenant = Tenant(
            id=PLATFORM_TENANT_ID,
            name="Platform Notification",
            slug=generate_id("platform"),
            status=LifecycleStatus.ACTIVE,
        )
        await session.merge(platform_tenant)

        # Add template to PLATFORM tenant
        template = NotificationTemplate(
            id=generate_id("tpl_plat"),
            tenant_id=PLATFORM_TENANT_ID,
            name="Platform Default",
            event_type=event_type,
            channel="EMAIL",
            is_active=True,
            subject_template="Alert",
            body_template="Alert Body",
        )
        session.add(template)

    async with db_session_factory() as session:
        repo = SqlAlchemyTemplateRepository(session)

        # Query using the regular tenant_id, it should fallback and find the PLATFORM template
        tmpl = await repo.get_template(tenant_id, event_type, Channel.EMAIL)

        assert tmpl is not None
        assert tmpl.tenant_id == PLATFORM_TENANT_ID
        assert tmpl.subject == "Alert"
