import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import ControlPlaneOutbox

from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.application.use_cases.webhooks import (
    CreateWebhookUseCase,
    DeleteWebhookUseCase,
    ListWebhooksUseCase,
    UpdateWebhookUseCase,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_webhook_lifecycle_integration(db_session: AsyncSession) -> None:
    """
    Narrow integration test for Webhook Use Cases.
    Uses the real PostgreSQL database and actual Repositories to test the full CRUD lifecycle
    and verifies that outbox events are properly committed to the database.
    """
    tenant_id = f"ten_{uuid.uuid4().hex[:12]}"

    # Create Use Cases
    uow = SqlAlchemyUcpUnitOfWork(db_session)
    create_uc = CreateWebhookUseCase(uow)
    update_uc = UpdateWebhookUseCase(uow)
    list_uc = ListWebhooksUseCase(uow)
    delete_uc = DeleteWebhookUseCase(uow)

    async with db_session.begin_nested():
        # 1. CREATE
        created_webhook = await create_uc.execute(
            tenant_id=tenant_id,
            name="Test Webhook",
            url="https://example.com/hook",
            auth_header_vault_ref=None,
        )

        assert created_webhook.id.startswith("web_")
        assert created_webhook.name == "Test Webhook"
        assert created_webhook.url == "https://example.com/hook"
        assert created_webhook.active is True

        # Verify outbox event was created in the DB
        stmt = select(ControlPlaneOutbox).where(ControlPlaneOutbox.tenant_id == tenant_id)
        outbox_records = (await db_session.execute(stmt)).scalars().all()
        assert len(outbox_records) == 1
        assert outbox_records[0].event_type == "webhook.created"

        payload = outbox_records[0].payload
        if isinstance(payload, str):
            payload = json.loads(payload)

        assert payload["webhook_id"] == created_webhook.id

        # Clear outbox for next test step
        for record in outbox_records:
            await db_session.delete(record)
        await db_session.flush()

        # 2. LIST
        webhooks = await list_uc.execute(tenant_id)
        assert len(webhooks) == 1
        assert webhooks[0].id == created_webhook.id

        # 3. UPDATE
        updated_webhook = await update_uc.execute(
            tenant_id=tenant_id,
            webhook_id=created_webhook.id,
            name="Updated Webhook",
            url=None,
            active=False,
        )
        assert updated_webhook.name == "Updated Webhook"
        assert updated_webhook.url == "https://example.com/hook"  # unchanged
        assert updated_webhook.active is False

        # Verify update outbox event
        outbox_records = (await db_session.execute(stmt)).scalars().all()
        assert len(outbox_records) == 1
        assert outbox_records[0].event_type == "webhook.updated"

        for record in outbox_records:
            await db_session.delete(record)
        await db_session.flush()

        # 4. DELETE
        await delete_uc.execute(tenant_id, created_webhook.id)

        # Verify delete outbox event
        outbox_records = (await db_session.execute(stmt)).scalars().all()
        assert len(outbox_records) == 1
        assert outbox_records[0].event_type == "webhook.deleted"

        # Verify no longer lists
        webhooks = await list_uc.execute(tenant_id)
        assert len(webhooks) == 0
