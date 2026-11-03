from collections.abc import Sequence
from typing import Protocol

from identity.domain.identity_context import PLATFORM_TENANT_ID
from outbox.domain.constants import OutboxStatus
from seedwork.events import DomainEvent
from seedwork.utils import generate_id
from sqlalchemy import select

from database.outbox_serializer import serialize_domain_event
from database.repository import BaseSqlAlchemyRepository as PlatformBaseSqlAlchemyRepository
from database.types import GlobalSession as GlobalSession
from database.types import TenantSession as TenantSession
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox


class DomainEventCarrier(Protocol):
    @property
    def domain_events(self) -> Sequence[DomainEvent]: ...

    def clear_domain_events(self) -> None: ...


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

    async def _drain_events(self, aggregate: DomainEventCarrier) -> None:
        for event in aggregate.domain_events:
            event_name = event.event_name
            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id() or PLATFORM_TENANT_ID

            if event.idempotency_key:
                res = await self.session.execute(
                    select(ControlPlaneOutbox).where(
                        ControlPlaneOutbox.idempotency_key == event.idempotency_key,
                        ControlPlaneOutbox.status == OutboxStatus.RESERVED,
                    )
                )
                reservation = res.scalar_one_or_none()
                if reservation is not None:
                    reservation.event_type = event_name
                    current_payload = reservation.payload or {}
                    if isinstance(current_payload, dict):
                        reservation.payload = {**current_payload, **payload_dict}
                    else:
                        reservation.payload = payload_dict
                    reservation.status = OutboxStatus.PENDING
                    continue

            outbox_id = generate_id(ControlPlaneOutbox.ID_PREFIX)
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
