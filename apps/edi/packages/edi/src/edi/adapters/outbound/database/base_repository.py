import os

from identity.domain.identity_context import PLATFORM_TENANT_ID
from outbox.domain.constants import OutboxStatus

from database.outbox_serializer import serialize_domain_event
from database.repository import BaseSqlAlchemyRepository as PlatformBaseSqlAlchemyRepository
from database.repository import HasDomainEvents
from database.types import GlobalSession as GlobalSession
from database.types import TenantSession as TenantSession
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox


class GlobalSqlAlchemyRepository(PlatformBaseSqlAlchemyRepository):
    """
    Base class for Control Plane repositories.
    Strictly enforces that the injected session is a GlobalSession.
    """

    session: GlobalSession

    def __init__(self, session: GlobalSession) -> None:
        info = session.info
        if isinstance(info, dict) and info.get("session_type") != "global":
            raise ValueError(
                f"Expected a GlobalSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session

    def _drain_events(self, aggregate: HasDomainEvents) -> None:
        for _index, event in enumerate(aggregate.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.event_name
            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id() or PLATFORM_TENANT_ID

            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=event.idempotency_key,
                tenant_id=tenant_id,
                event_type=event_name,
                payload=payload_dict,
                status=OutboxStatus.PENDING,
            )
            self.session.add(outbox_event)

        aggregate.clear_domain_events()


class TenantSqlAlchemyRepository(PlatformBaseSqlAlchemyRepository):
    """
    Base class for Data Plane / Shard repositories.
    Strictly enforces that the injected session is a TenantSession.
    """

    session: TenantSession

    def __init__(self, session: TenantSession) -> None:
        info = session.info
        if isinstance(info, dict) and info.get("session_type") != "tenant":
            raise ValueError(
                f"Expected a TenantSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session
