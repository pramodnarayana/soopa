from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from edi.adapters.outbound.database.outbox_repository import (
    SqlAlchemyControlPlaneOutboxRepository,
)
from edi.domain.events import EdiEventType, ProvisioningEvent


@pytest.mark.asyncio
async def test_publish_finalizes_existing_idempotency_reservation():
    session = AsyncMock()
    reservation = SimpleNamespace(
        id="reservation-request-1",
        event_type="RESERVATION",
        payload={"fingerprint": "fingerprint-1"},
        status="RESERVED",
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = reservation
    session.execute.return_value = result
    repository = SqlAlchemyControlPlaneOutboxRepository(session)

    event_id = await repository.publish_outbox_event(
        ProvisioningEvent(
            tenant_id="tenant-1",
            event_type=EdiEventType.edi_as2_partner_created,
            resource_id="partner-1",
        ),
        idempotency_key="request-1",
    )

    assert event_id == "reservation-request-1"
    assert reservation.status == "PENDING"
    assert reservation.event_type == "edi.as2_partner.created"
    assert reservation.payload == {
        "fingerprint": "fingerprint-1",
        "tenant_id": "tenant-1",
        "event_type": "edi.as2_partner.created",
        "resource_id": "partner-1",
    }
