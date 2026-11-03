import json

import pytest
from seedwork import generate_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import UcpOutbox

from ucp.application.use_cases.webhooks import (
    CreateWebhookUseCase,
    DeleteWebhookUseCase,
    ListWebhooksUseCase,
    UpdateWebhookUseCase,
)
from ucp.bootstrap.container import create_ucp_uow
from ucp.domain.constants import UcpIdPrefix as DomainIdPrefix

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_webhook_lifecycle_integration(db_session: AsyncSession) -> None:
    """
    Narrow integration test for Webhook Use Cases.
    Uses the real PostgreSQL database and actual Repositories to test the full CRUD lifecycle
    and verifies that outbox events are properly committed to the database.
    """
    tenant_id = generate_id(DomainIdPrefix.TENANT.value)

    uow = create_ucp_uow(db_session)
    create_uc = CreateWebhookUseCase(uow)
    update_uc = UpdateWebhookUseCase(uow)
    list_uc = ListWebhooksUseCase(uow)
    delete_uc = DeleteWebhookUseCase(uow)

    # 1. CREATE
    create_res = await create_uc.execute(
        tenant_id=tenant_id,
        name="Test Webhook",
        url="https://example.com/hook",
        auth_header_vault_ref=None,
    )
    assert create_res.is_ok
    created_webhook = create_res.unwrap()

    assert created_webhook.id.startswith("ucp_wh_")
    assert created_webhook.name == "Test Webhook"
    assert created_webhook.url == "https://example.com/hook"
    assert created_webhook.active is True

    stmt = select(UcpOutbox).where(UcpOutbox.tenant_id == tenant_id)
    outbox_records = (await db_session.execute(stmt)).scalars().all()
    assert len(outbox_records) == 1
    assert outbox_records[0].event_type == "webhook.created"

    payload = outbox_records[0].payload
    if isinstance(payload, str):
        payload = json.loads(payload)

    assert payload["webhook_id"] == created_webhook.id

    for record in outbox_records:
        await db_session.delete(record)
    await db_session.flush()

    # 2. LIST
    webhooks = await list_uc.execute(tenant_id)
    assert len(webhooks) == 1
    assert webhooks[0].id == created_webhook.id

    # 3. UPDATE
    update_res = await update_uc.execute(
        tenant_id=tenant_id,
        webhook_id=created_webhook.id,
        name="Updated Webhook",
        url=None,
        active=False,
    )
    assert update_res.is_ok
    updated_webhook = update_res.unwrap()
    assert updated_webhook.name == "Updated Webhook"
    assert updated_webhook.url == "https://example.com/hook"
    assert updated_webhook.active is False

    outbox_records = (await db_session.execute(stmt)).scalars().all()
    assert len(outbox_records) == 1
    assert outbox_records[0].event_type == "webhook.updated"

    for record in outbox_records:
        await db_session.delete(record)
    await db_session.flush()

    # 4. DELETE
    del_res = await delete_uc.execute(
        tenant_id=tenant_id,
        webhook_id=created_webhook.id,
        deleted_by="test-runner",
    )
    assert del_res.is_ok

    outbox_records = (await db_session.execute(stmt)).scalars().all()
    assert len(outbox_records) == 1
    assert outbox_records[0].event_type == "webhook.deleted"

    webhooks = await list_uc.execute(tenant_id)
    assert len(webhooks) == 0
