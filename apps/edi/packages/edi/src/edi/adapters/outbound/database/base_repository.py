import os

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
        info = getattr(session, "info", {})
        if isinstance(info, dict) and info.get("session_type") != "global":
            raise ValueError(
                f"Expected a GlobalSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session

    def _drain_events(self, aggregate: HasDomainEvents, idempotency_key: str | None = None) -> None:
        for index, event in enumerate(aggregate.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.event_name
            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id() or getattr(aggregate, "tenant_id", None)

            fallback_id = getattr(
                event, "id", getattr(event, "resource_id", getattr(aggregate, "id", ""))
            )
            final_idemp_key = (
                f"{idempotency_key}_{index}"
                if idempotency_key
                else f"{event_name}_{tenant_id}_{fallback_id}_{index}"
            )

            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=final_idemp_key,
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
        info = getattr(session, "info", {})
        if isinstance(info, dict) and info.get("session_type") != "tenant":
            raise ValueError(
                f"Expected a TenantSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session
