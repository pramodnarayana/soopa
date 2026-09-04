import pytest
from database.testing import TransactionalTestRouter

from edi.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent


class EventAggregate:
    def __init__(self, event: ProvisioningEvent) -> None:
        self.id = "aggregate-1"
        self.tenant_id = "tenant-1"
        self.domain_events = [event]

    def clear_domain_events(self) -> None:
        self.domain_events.clear()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_drain_events_prefers_explicit_event_idempotency_key(
    db_router: TransactionalTestRouter,
) -> None:
    async for session in db_router.get_global_session():
        repository = GlobalSqlAlchemyRepository(session)
        aggregate = EventAggregate(
            ProvisioningEvent(
                tenant_id="tenant-1",
                event_type=EdiEventType.edi_as2_partner_created,
                resource_id="partner-1",
                explicit_idempotency_key="request-1",
            )
        )

        repository._drain_events(aggregate)

        # The outbox event is added to the session
        added_objects = list(session.new)
        assert len(added_objects) == 1

        outbox_event = added_objects[0]
        assert isinstance(outbox_event, ControlPlaneOutbox)
        assert outbox_event.idempotency_key == "request-1"
        assert aggregate.domain_events == []
        break
