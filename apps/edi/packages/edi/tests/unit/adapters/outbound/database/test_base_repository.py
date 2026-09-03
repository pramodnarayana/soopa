from typing import cast
from unittest.mock import MagicMock

from database.repository import HasDomainEvents
from database.types import GlobalSession

from edi.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent


class EventAggregate:
    def __init__(self, event: ProvisioningEvent) -> None:
        self.id = "aggregate-1"
        self.tenant_id = "tenant-1"
        self.domain_events = [event]

    def clear_domain_events(self) -> None:
        self.domain_events.clear()


def test_drain_events_prefers_explicit_event_idempotency_key() -> None:
    session = MagicMock()
    repository = GlobalSqlAlchemyRepository(cast(GlobalSession, session))
    aggregate = EventAggregate(
        ProvisioningEvent(
            tenant_id="tenant-1",
            event_type=EdiEventType.edi_as2_partner_created,
            resource_id="partner-1",
            explicit_idempotency_key="request-1",
        )
    )

    repository._drain_events(cast(HasDomainEvents, aggregate))

    outbox_event = session.add.call_args.args[0]
    assert outbox_event.idempotency_key == "request-1"
    assert aggregate.domain_events == []
