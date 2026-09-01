import uuid

import pytest
import pytest_asyncio
from outbox.domain.constants import OutboxStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from edi.adapters.outbound.database.outbox_repository import (
    SqlAlchemyControlPlaneOutboxRepository,
)
from edi.domain.events import EdiEventType, ProvisioningEvent


@pytest_asyncio.fixture
async def global_session(db_connection):
    SessionLocal = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        info={"session_type": "global"},
    )
    async with SessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_publish_finalizes_existing_idempotency_reservation(global_session):
    repository = SqlAlchemyControlPlaneOutboxRepository(global_session)
    idempotency_key = f"request-{uuid.uuid4()}"
    tenant_id = "tenant-1"

    # Pre-seed a RESERVED outbox event using the ORM model
    reservation_id = f"res-{uuid.uuid4()}"
    reserved_outbox = ControlPlaneOutbox(
        id=reservation_id,
        idempotency_key=idempotency_key,
        tenant_id=tenant_id,
        event_type="RESERVATION",
        payload={"fingerprint": "fingerprint-1"},
        status=OutboxStatus.RESERVED.value,
        attempts=0,
    )
    global_session.add(reserved_outbox)
    await global_session.flush()

    event_id = await repository.publish_outbox_event(
        ProvisioningEvent(
            tenant_id=tenant_id,
            event_type=EdiEventType.edi_as2_partner_created,
            resource_id="partner-1",
        ),
        idempotency_key=idempotency_key,
    )

    # Repository should return the existing ID
    assert event_id == reservation_id

    # Verify DB state using ORM
    result = await global_session.execute(
        select(ControlPlaneOutbox).where(ControlPlaneOutbox.id == reservation_id)
    )
    updated_outbox = result.scalar_one_or_none()

    assert updated_outbox is not None
    assert updated_outbox.status == OutboxStatus.PENDING.value
    assert updated_outbox.event_type == "edi.as2_partner.created"

    # Assert payload was merged
    assert updated_outbox.payload["fingerprint"] == "fingerprint-1"
    assert updated_outbox.payload["tenant_id"] == tenant_id
    assert updated_outbox.payload["event_type"] == "edi.as2_partner.created"
    assert updated_outbox.payload["resource_id"] == "partner-1"
