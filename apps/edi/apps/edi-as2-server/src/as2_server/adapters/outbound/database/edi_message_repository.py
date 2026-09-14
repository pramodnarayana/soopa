import uuid
from typing import Any

from edi.adapters.outbound.database.models.data_plane import EdiMessage
from edi.domain.constants import EDI_MESSAGE_ID_PREFIX
from seedwork import generate_random_hex
from sqlalchemy.ext.asyncio import AsyncSession


class EdiMessageRepositoryAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_message(
        self,
        tenant_id: str,
        trace_id: uuid.UUID | str,
        direction: str,
        connection_type: str,
        sender_id: str,
        receiver_id: str,
        edi_data: str,
        status: str,
        as2_message_id: str,
    ) -> None:

        record = EdiMessage(
            id=f"{EDI_MESSAGE_ID_PREFIX}_{generate_random_hex(6)}",
            tenant_id=tenant_id,
            trace_id=str(trace_id),
            direction=direction,
            connection_type=connection_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            edi_data=edi_data,
            status=status,
            message_id=as2_message_id,
        )
        self.session.add(record)
        await self.session.flush()


class EdiMessageRepositoryFactory:
    """Implements EdiMessageRepositoryFactoryPort to create tenant-scoped repo instances."""

    def create_repo(self, tenant_session: Any) -> EdiMessageRepositoryAdapter:
        return EdiMessageRepositoryAdapter(tenant_session)
