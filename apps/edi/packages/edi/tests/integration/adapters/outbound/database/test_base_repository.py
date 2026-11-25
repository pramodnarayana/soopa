import pytest
from database.models.config_sync import ConfigChangelogEntry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class EventAggregate:
    def __init__(self, event: ProvisioningEvent) -> None:
        self.id = "aggregate-1"
        self.tenant_id = "tenant-1"
        self.domain_events = [event]

    def clear_domain_events(self) -> None:
        self.domain_events.clear()


async def test_drain_events_prefers_explicit_event_idempotency_key(
    db_session: AsyncSession,
) -> None:
    db_session.info["session_type"] = "global"
    repository = GlobalSqlAlchemyRepository(db_session)
    aggregate = EventAggregate(
        ProvisioningEvent(
            tenant_id="tenant-1",
            event_type=EdiEventType.edi_as2_partner_created,
            resource_id="partner-1",
            idempotency_key="request-1",
        )
    )

    await repository._drain_events(aggregate)
    await db_session.flush()

    outbox_rows = list(
        (
            await db_session.execute(
                select(ControlPlaneOutbox).where(ControlPlaneOutbox.idempotency_key == "request-1")
            )
        )
        .scalars()
        .all()
    )
    assert len(outbox_rows) == 1
    outbox_event = outbox_rows[0]
    assert isinstance(outbox_event, ControlPlaneOutbox)
    assert outbox_event.idempotency_key == "request-1"

    changelog_rows = list(
        (
            await db_session.execute(
                select(ConfigChangelogEntry).where(
                    ConfigChangelogEntry.tenant_id == "tenant-1",
                    ConfigChangelogEntry.entity_id == "partner-1",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(changelog_rows) == 1
    assert aggregate.domain_events == []
