import uuid
from typing import Any

from database.models import ApiGateway, EdiMessage
from database.models import TenantOutbox as Outbox
from database.models.data_plane import (
    AS2Partner,
    AS2Partnership,
    InboundRoute,
    OutboundRoute,
    SFTPPartner,
    WebhookPartner,
)
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
            "tenant_id": record.tenant_id,
            "edi_data": record.edi_data,
            "format_standard": record.format_standard,
            "transaction_type": record.transaction_type,
            "sender_id": record.sender_id,
            "receiver_id": record.receiver_id,
            "direction": record.direction,
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
        record = ApiGateway(
            trace_id=uuid.UUID(trace_id),
            direction=direction,
            request=s3_uri,
            status=status,
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
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def claim_edi_message(self, trace_id: str) -> bool:
        stmt = (
            update(EdiMessage)
            .where(
                EdiMessage.trace_id == uuid.UUID(trace_id),
                EdiMessage.status == "PENDING_DELIVERY",
            )
            .values(status="PROCESSING")
            .returning(EdiMessage.id)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none() is not None

    async def get_api_payload(self, trace_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(ApiGateway).where(ApiGateway.trace_id == uuid.UUID(trace_id))
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "trace_id": str(record.trace_id),
            "request": record.request,
            "status": record.status,
            "direction": record.direction,
        }

    async def update_api_payload_status(self, trace_id: str, status: str) -> None:
        await self.session.execute(
            update(ApiGateway)
            .where(ApiGateway.trace_id == uuid.UUID(trace_id))
            .values(status=status)
        )
        await self.session.flush()

    async def claim_api_payload(self, trace_id: str) -> bool:
        stmt = (
            update(ApiGateway)
            .where(
                ApiGateway.trace_id == uuid.UUID(trace_id),
                ApiGateway.status == "PENDING_DELIVERY",
            )
            .values(status="PROCESSING")
            .returning(ApiGateway.id)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none() is not None

    async def get_route(
        self, direction: str, sender_id: str, receiver_id: str, transaction_type: str
    ) -> dict[str, Any] | None:
        if direction not in ("INBOUND", "OUTBOUND"):
            raise ValueError(f"Invalid direction: {direction}")
        model = InboundRoute if direction == "INBOUND" else OutboundRoute

        # Exact match or wildcard transaction type
        stmt = select(model).where(
            model.isa_sender_id == sender_id,
            model.isa_receiver_id == receiver_id,
            model.transaction_type.in_([transaction_type, "*"]),
            model.active.is_(True),
        )

        result = await self.session.execute(stmt)
        # Fetch all matches, prefer exact transaction_type over wildcard
        records = list(result.scalars().all())
        if not records:
            return None

        # Sort so specific transaction types match before generic "*"
        records = sorted(records, key=lambda r: getattr(r, "transaction_type", "*") == "*")

        # mypy gets confused by TenantBase being the base class but returning specific derived models
        record: Any = records[0]
        return {
            "route_id": str(record.id),
            "as2_partner_id": str(record.as2_partner_id) if record.as2_partner_id else None,
            "sftp_partner_id": str(record.sftp_partner_id) if record.sftp_partner_id else None,
            "webhook_partner_id": str(record.webhook_partner_id)
            if hasattr(record, "webhook_partner_id") and record.webhook_partner_id
            else None,
        }

    async def get_sftp_partner(self, partner_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id == uuid.UUID(partner_id), SFTPPartner.active.is_(True)
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "name": record.name,
            "host": record.host,
            "port": record.port,
            "username": record.username,
            "remote_path": record.remote_path,
            "credentials_vault_ref": record.credentials_vault_ref,
        }

    async def get_webhook_partner(self, partner_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(WebhookPartner).where(
                WebhookPartner.id == uuid.UUID(partner_id), WebhookPartner.active.is_(True)
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "name": record.name,
            "url": record.url,
            "auth_header_vault_ref": record.auth_header_vault_ref,
        }

    async def get_as2_partner(self, partner_id: str) -> dict[str, Any] | None:
        stmt = (
            select(AS2Partner, AS2Partnership)
            .join(AS2Partnership, AS2Partnership.remote_partner_id == AS2Partner.id)
            .where(
                AS2Partner.id == uuid.UUID(partner_id),
                AS2Partner.active.is_(True),
                AS2Partnership.active.is_(True),
            )
        )
        result = await self.session.execute(stmt)
        record = result.first()
        if not record:
            return None
        partner, partnership = record
        return {
            "name": partner.name,
            "as2_id": partner.as2_id,
            "public_cert_pem": partner.public_cert_pem,
            "public_cert_vault_ref": partner.public_cert_vault_ref,
            "local_url": partnership.local_url,
            "remote_url": partnership.remote_url,
            "local_partner_id": str(partnership.local_partner_id),
            "credentials_vault_ref": partnership.credentials_vault_ref,
            "encryption_algorithm": partnership.encryption_algorithm,
            "signature_algorithm": partnership.signature_algorithm,
            "mdn_type": partnership.mdn_type,
            "mdn_url": partnership.mdn_url,
        }

    async def get_local_as2_partner(self, partner_id: str) -> dict[str, Any] | None:
        """Fetches the local (our) AS2 partner to retrieve signing key and cert refs."""
        result = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.id == uuid.UUID(partner_id),
                AS2Partner.active.is_(True),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "name": record.name,
            "as2_id": record.as2_id,
            "public_cert_pem": record.public_cert_pem,
            "public_cert_vault_ref": record.public_cert_vault_ref,
            "private_key_vault_ref": record.private_key_vault_ref,
        }
