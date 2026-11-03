import uuid

import pytest
import pytest_asyncio
from identity.domain.identity_context import PLATFORM_TENANT_ID
from outbox.domain.constants import OutboxStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from edi.adapters.outbound.database.control_plane.as2_partner_repository import (
    SqlAlchemyAS2TradingPartnerRepository,
)
from edi.adapters.outbound.database.control_plane.outbox_repository import (
    SqlAlchemyControlPlaneOutboxRepository,
)
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from edi.domain.partner.as2.partner import AS2Partner

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def global_session(db_connection: AsyncSession) -> AsyncSession:
    session_local = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        info={"session_type": "global"},
    )
    async with session_local() as session:
        yield session


@pytest.mark.asyncio
async def test_save_finalizes_existing_idempotency_reservation(
    global_session: AsyncSession,
) -> None:
    outbox_repo = SqlAlchemyControlPlaneOutboxRepository(global_session)
    partner_repo = SqlAlchemyAS2TradingPartnerRepository(global_session)
    idempotency_key = f"request-{uuid.uuid4()}"

    await outbox_repo.create_reservation(
        tenant_id=PLATFORM_TENANT_ID,
        idempotency_key=idempotency_key,
        fingerprint="fingerprint-1",
    )

    partner = AS2Partner.create(
        tenant_id=PLATFORM_TENANT_ID,
        name="Acme Partner",
        as2_id=f"ACME_{uuid.uuid4().hex[:8]}",
        is_local=False,
        url="https://acme.example.com/as2",
        public_cert_pem="-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
        idempotency_key=idempotency_key,
    ).unwrap()

    await partner_repo.save(partner)

    result = await global_session.execute(
        select(ControlPlaneOutbox).where(ControlPlaneOutbox.idempotency_key == idempotency_key)
    )
    updated_outbox = result.scalar_one_or_none()

    assert updated_outbox is not None
    assert updated_outbox.id == f"reservation_{idempotency_key}"
    assert updated_outbox.status == OutboxStatus.PENDING.value
    assert updated_outbox.event_type == "edi.as2_partner.created"
    assert updated_outbox.payload["fingerprint"] == "fingerprint-1"
    assert updated_outbox.payload["tenant_id"] == PLATFORM_TENANT_ID
    assert updated_outbox.payload["event_type"] == "edi.as2_partner.created"
    assert updated_outbox.payload["resource_id"] == partner.id
