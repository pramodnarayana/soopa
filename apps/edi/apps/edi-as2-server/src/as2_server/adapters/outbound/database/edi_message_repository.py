import typing

from database.outbox_serializer import serialize_domain_event
from edi.adapters.outbound.database.models.data_plane import DataPlaneOutbox
from edi.adapters.outbound.database.models.data_plane import EdiMessage as OrmEdiMessage
from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.enums import EdiOutboxSource
from outbox.domain.constants import OutboxStatus
from seedwork import generate_id
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from sqlalchemy.ext.asyncio import AsyncSession

if typing.TYPE_CHECKING:
    from edi.domain.transaction.edi_message import EdiMessage


class SqlAlchemyAS2EdiMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_orm_record(aggregate: "EdiMessage") -> OrmEdiMessage:
        return OrmEdiMessage(
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

    async def save_message(self, aggregate: "EdiMessage") -> list["EventEnvelope"]:
        record = self._to_orm_record(aggregate)
        self.session.add(record)

        envelopes = []
        for event in aggregate.domain_events:
            payload_json = serialize_domain_event(event)
            event_id = generate_id(DomainIdPrefix.EDI_DP_OUTBOX)
            ik = event.idempotency_key or generate_id(SystemIdPrefix.IDEMPOTENCY)
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


class SqlAlchemyAS2EdiMessageRepositoryFactory:
    """Implements EdiMessageRepositoryFactoryPort to create tenant-scoped repo instances."""

    def create_repo(self, tenant_session: AsyncSession) -> SqlAlchemyAS2EdiMessageRepository:
        return SqlAlchemyAS2EdiMessageRepository(tenant_session)
