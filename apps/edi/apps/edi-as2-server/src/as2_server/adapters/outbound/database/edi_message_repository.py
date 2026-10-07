import typing
import uuid
from typing import Any

from database.outbox_serializer import serialize_domain_event
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox, EdiMessage
from edi.domain.enums import EdiOutboxSource
from outbox.domain.constants import OutboxStatus
from seedwork import generate_id
from seedwork.events import EventEnvelope
from seedwork.id_registry import DomainIdPrefix
from sqlalchemy.ext.asyncio import AsyncSession

if typing.TYPE_CHECKING:
    from edi.domain.models.transactions import EdiMessageDomainModel


class EdiMessageRepositoryAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_message(self, aggregate: "EdiMessageDomainModel") -> list["EventEnvelope"]:
        record = EdiMessage(
            id=aggregate.id,
            tenant_id=aggregate.tenant_id,
            trace_id=aggregate.trace_id,
            direction=aggregate.direction,
            connection_type=aggregate.connection_type,
            sender_id=aggregate.sender_id,
            receiver_id=aggregate.receiver_id,
            edi_data=aggregate.edi_data,
            status=aggregate.status,
            message_id=aggregate.message_id,
        )
        self.session.add(record)

        envelopes = []
        for event in aggregate.domain_events:
            payload_json = serialize_domain_event(event)
            event_id = generate_id(DomainIdPrefix.EDI_DP_OUTBOX)
            ik = getattr(event, "trace_id", None) or str(uuid.uuid4())
            outbox_record = DataPlaneOutbox(
                id=event_id,
                tenant_id=aggregate.tenant_id,
                idempotency_key=ik,
                event_type=event.event_name,
                payload=payload_json,
                status=OutboxStatus.PENDING.value,
            )
            self.session.add(outbox_record)
            envelopes.append(
                EventEnvelope(
                    id=event_id,
                    source=EdiOutboxSource.EDI_DATA_PLANE,
                    event_type=event.event_name,
                    payload=payload_json,
                    idempotency_key=ik,
                    tenant_id=aggregate.tenant_id,
                )
            )

        aggregate.clear_domain_events()
        await self.session.flush()
        return envelopes


class EdiMessageRepositoryFactory:
    """Implements EdiMessageRepositoryFactoryPort to create tenant-scoped repo instances."""

    def create_repo(self, tenant_session: Any) -> EdiMessageRepositoryAdapter:
        return EdiMessageRepositoryAdapter(tenant_session)
