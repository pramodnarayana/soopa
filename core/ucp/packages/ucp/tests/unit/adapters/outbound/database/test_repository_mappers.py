"""Pure zero-mock Phase 4 unit tests for UCP SQLAlchemy Data Mappers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from database.models import Webhook as DbWebhook
from database.models.identity import Tenant as DbTenant
from database.provider import DatabaseProvider
from identity.domain.constants import TenantIsolationMode
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import event
from ucp_models.subscriptions import App as DbApp

from ucp.adapters.outbound.database.app_repository import SqlAlchemyAppRepository
from ucp.adapters.outbound.database.tenant_query_service import SqlAlchemyTenantQueryService
from ucp.adapters.outbound.database.tenant_repository import SqlAlchemyTenantRepository
from ucp.adapters.outbound.database.webhook_repository import SqlAlchemyWebhookRepository
from ucp.bootstrap.container import create_ucp_uow
from ucp.domain.constants import LifecycleStatus, UcpIdPrefix
from ucp.domain.tenant import Tenant, TenantSubscription
from ucp.domain.webhook import Webhook


def test_tenant_repository_mappers_preserve_slug_immutability() -> None:
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    tenant_id_1 = generate_id(UcpIdPrefix.TENANT.value)
    tenant_id_2 = generate_id(UcpIdPrefix.TENANT.value)
    app_id = generate_id(UcpIdPrefix.APP.value)
    idp_org_1 = generate_id(SystemIdPrefix.GENERIC.value)
    idp_org_2 = generate_id(SystemIdPrefix.GENERIC.value)

    row = DbTenant(
        id=tenant_id_1,
        name="Acme Logistics",
        slug="acme-logistics",
        idp_realm_name=idp_org_1,
        isolation_mode=TenantIsolationMode.POOLED_REALM.value,
        status=LifecycleStatus.ACTIVE.value,
        created_at=now_naive,
        updated_at=now_naive,
    )
    subs = [TenantSubscription(app_id=app_id, status=LifecycleStatus.ACTIVE)]

    domain_tenant = SqlAlchemyTenantRepository._to_domain_model(row, subs)
    assert domain_tenant.id == tenant_id_1
    assert domain_tenant.slug == "acme-logistics"
    assert domain_tenant.created_at.tzinfo == UTC
    assert len(domain_tenant.subscriptions) == 1

    domain_tenant.rename("Acme Global Logistics")
    domain_tenant.change_status(LifecycleStatus.INACTIVE)
    SqlAlchemyTenantRepository._update_record_from_domain(row, domain_tenant)
    assert row.name == "Acme Global Logistics"
    assert row.slug == "acme-logistics"
    assert row.status == LifecycleStatus.INACTIVE.value

    fresh_tenant = Tenant.create(
        id=tenant_id_2,
        name="Beta Corp",
        slug="beta-corp",
        idp_realm_name=idp_org_2,
    ).unwrap()
    orm_tenant = SqlAlchemyTenantRepository._to_orm_record(fresh_tenant)
    assert orm_tenant.id == tenant_id_2
    assert orm_tenant.slug == "beta-corp"
    assert orm_tenant.created_at.tzinfo is None


def test_webhook_app_and_tenant_query_mappers() -> None:
    tenant_id = generate_id(UcpIdPrefix.TENANT.value)
    webhook_id = generate_id(UcpIdPrefix.WEBHOOK.value)
    app_id = generate_id(UcpIdPrefix.APP.value)
    idp_proj_id = generate_id(SystemIdPrefix.GENERIC.value)
    idp_org_id = generate_id(SystemIdPrefix.GENERIC.value)

    webhook = Webhook.create(
        id=webhook_id,
        tenant_id=tenant_id,
        name="Order Hook",
        url="https://erp.acme.test/orders",
        auth_header_vault_ref=f"vault://wh/{webhook_id}",
    ).unwrap()

    orm_webhook: DbWebhook = SqlAlchemyWebhookRepository._to_orm_record(webhook)
    assert orm_webhook.id == webhook_id
    assert orm_webhook.created_at.tzinfo is None

    mapped_webhook = SqlAlchemyWebhookRepository._to_domain_model(orm_webhook)
    assert mapped_webhook.url == "https://erp.acme.test/orders"
    assert mapped_webhook.created_at.tzinfo == UTC

    mapped_webhook.update(name="Updated Order Hook", active=False)
    SqlAlchemyWebhookRepository._update_record_from_domain(orm_webhook, mapped_webhook)
    assert orm_webhook.name == "Updated Order Hook"
    assert orm_webhook.active is False

    db_app = DbApp(
        id=app_id,
        slug="edi",
        name="EDI Cloud",
        description=None,
        idp_project_id=idp_proj_id,
    )
    app = SqlAlchemyAppRepository._to_domain_model(db_app)
    assert app.id == app_id
    assert app.description == ""
    assert app.idp_project_id == idp_proj_id

    now_naive = datetime.now(UTC).replace(tzinfo=None)
    db_tenant = DbTenant(
        id=tenant_id,
        name="Acme Logistics",
        slug="acme-logistics",
        idp_realm_name=idp_org_id,
        isolation_mode=TenantIsolationMode.POOLED_REALM.value,
        status=LifecycleStatus.ACTIVE.value,
        created_at=now_naive,
        updated_at=now_naive,
    )
    read_model = SqlAlchemyTenantQueryService._to_read_model(db_tenant, ["edi", "billing"])
    assert read_model.id == tenant_id
    assert read_model.subscriptions == ["edi", "billing"]
    assert read_model.created_at.tzinfo == UTC


@pytest.mark.asyncio
async def test_ucp_uow_pre_commit_emits_no_notify_sql() -> None:
    provider = DatabaseProvider.from_url("sqlite+aiosqlite:///:memory:")
    executed_statements: list[str] = []

    def _capture_do_execute(
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
    ) -> bool | None:
        del cursor, parameters, context
        executed_statements.append(statement)
        return None

    event.listen(provider.engine.sync_engine, "do_execute", _capture_do_execute, retval=True)
    try:
        async with provider.session_factory() as session:
            uow = create_ucp_uow(session=session)
            await uow._pre_commit()
    finally:
        event.remove(provider.engine.sync_engine, "do_execute", _capture_do_execute)
        await provider.engine.dispose()

    assert executed_statements == []
