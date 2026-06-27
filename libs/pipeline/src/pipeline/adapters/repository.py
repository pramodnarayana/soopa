import uuid
from typing import Any

from database.models import ApiPayload, EdiMessage
from database.models import TenantOutbox as Outbox
from pipeline.ports.repository import RepositoryPort
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyRepositoryAdapter(RepositoryPort):
    """
    Concrete implementation of RepositoryPort using SQLAlchemy AsyncSession.
    Operates on the Tenant Data Plane models.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_edi_message(self, trace_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(EdiMessage).where(EdiMessage.trace_id == uuid.UUID(trace_id))
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "trace_id": str(record.trace_id),
            "s3_key": record.s3_key,
            "format_standard": record.format_standard,
            "transaction_type": record.transaction_type,
            "status": record.status,
        }

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        await self.session.execute(
            update(EdiMessage)
            .where(EdiMessage.trace_id == uuid.UUID(trace_id))
            .values(status=status)
        )
        await self.session.flush()

    async def save_api_payload(
        self, trace_id: str, direction: str, s3_uri: str, status: str
    ) -> None:
        record = ApiPayload(
            trace_id=uuid.UUID(trace_id),
            direction=direction,
            s3_key=s3_uri,
            status=status,
            # tenant_id is automatically injected by the Hybrid Tenancy Context session
        )
        self.session.add(record)
        await self.session.flush()

    async def publish_outbox_event(
        self, idempotency_key: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        stmt = (
            insert(Outbox)
            .values(
                idempotency_key=uuid.UUID(idempotency_key),
                event_type=event_type,
                payload=payload,
                status="PENDING",
                # tenant_id is automatically injected by the Hybrid Tenancy Context session
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_api_payload(self, trace_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(ApiPayload).where(ApiPayload.trace_id == uuid.UUID(trace_id))
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "trace_id": str(record.trace_id),
            "s3_key": record.s3_key,
            "status": record.status,
        }

    async def update_api_payload_status(self, trace_id: str, status: str) -> None:
        await self.session.execute(
            update(ApiPayload)
            .where(ApiPayload.trace_id == uuid.UUID(trace_id))
            .values(status=status)
        )
        await self.session.flush()

    async def claim_api_payload(self, trace_id: str) -> bool:
        stmt = (
            update(ApiPayload)
            .where(
                ApiPayload.trace_id == uuid.UUID(trace_id),
                ApiPayload.status == "PENDING_DELIVERY",
            )
            .values(status="PROCESSING")
            .returning(ApiPayload.id)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none() is not None
