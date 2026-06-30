import uuid
from typing import Any
from uuid import UUID

from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
)
from api.ports.repository import (
    ControlPlaneRepositoryPort,
    DataPlaneRepositoryPort,
    TenantRepositoryPort,
)
from database.models.control_plane import AS2Partner, AS2Partnership, Tenant
from database.models.control_plane import Outbox as GlobalOutbox
from database.models.data_plane import (
    AS2Partner as DataPlaneAS2Partner,
)
from database.models.data_plane import (
    InboundRoute,
    OutboundRoute,
    SFTPPartner,
    WebhookPartner,
)
from identity.tenant_context import get_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyControlPlaneRepository(ControlPlaneRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_as2_identity(self, tenant_id: int, cmd: CreateAS2TradingPartnerCmd) -> UUID:
        partner_id = uuid.uuid4()
        record = AS2Partner(
            id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            as2_id=cmd.as2_id,
            is_local=cmd.is_local,
            public_cert_pem=cmd.public_cert_pem,
            public_cert_vault_ref=cmd.public_cert_vault_ref,
            private_key_vault_ref=cmd.private_key_vault_ref,
            active=True,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def create_as2_partnership(self, tenant_id: int, cmd: CreateAS2PartnershipCmd) -> UUID:
        partnership_id = uuid.uuid4()
        record = AS2Partnership(
            id=partnership_id,
            tenant_id=tenant_id,
            local_partner_id=cmd.local_partner_id,
            remote_partner_id=cmd.remote_partner_id,
            local_url=cmd.local_url,
            remote_url=cmd.remote_url,
            credentials_vault_ref=cmd.credentials_vault_ref,
            mdn_type=cmd.mdn_type,
            mdn_url=cmd.mdn_url,
            encryption_algorithm=cmd.encryption_algorithm,
            signature_algorithm=cmd.signature_algorithm,
            advanced_flags=cmd.advanced_flags,
            active=True,
        )
        self.session.add(record)
        await self.session.flush()

        await self.create_outbox_event(
            tenant_id=tenant_id,
            event_type="AS2_PARTNERSHIP_CREATED",
            payload={"partnership_id": str(partnership_id), "tenant_id": tenant_id},
        )

        return partnership_id

    async def get_as2_partners_by_ids(self, ids: list[UUID], tenant_id: int) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(AS2Partner.id, AS2Partner.name).where(
                AS2Partner.id.in_(ids),
                (AS2Partner.tenant_id == tenant_id) | (AS2Partner.tenant_id.is_(None)),
            )
        )
        return {row.id: row.name for row in result.all()}

    async def create_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> UUID:
        event_id = uuid.uuid4()
        record = GlobalOutbox(
            id=event_id,
            tenant_id=tenant_id,
            idempotency_key=uuid.uuid4(),
            event_type=event_type,
            payload=payload,
            status="PENDING",
        )
        self.session.add(record)
        await self.session.flush()
        return event_id


class SqlAlchemyDataPlaneRepository(DataPlaneRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _tenant_id(self) -> int:
        tenant_id = get_tenant_id()
        if tenant_id is None:
            raise RuntimeError("Database queries require an active tenant context.")
        return tenant_id

    async def create_sftp_partner(self, cmd: CreateSFTPPartnerCmd) -> UUID:
        partner_id = uuid.uuid4()
        record = SFTPPartner(
            id=partner_id,
            tenant_id=self._tenant_id(),
            name=cmd.name,
            host=cmd.host,
            port=cmd.port,
            username=cmd.username,
            remote_path=cmd.remote_path,
            credentials_vault_ref=cmd.credentials_vault_ref,
            active=True,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def get_sftp_partners_by_ids(self, ids: list[UUID]) -> dict[UUID, str]:
        """Returns a dict mapping SFTP Partner ID to Name."""
        if not ids:
            return {}
        result = await self.session.execute(
            select(SFTPPartner.id, SFTPPartner.name).where(
                SFTPPartner.id.in_(ids), SFTPPartner.tenant_id == self._tenant_id()
            )
        )
        return {row.id: row.name for row in result.all()}

    async def get_webhook_partners_by_ids(self, ids: list[UUID]) -> dict[UUID, str]:
        """Returns a dict mapping Webhook Partner ID to Name."""
        if not ids:
            return {}
        result = await self.session.execute(
            select(WebhookPartner.id, WebhookPartner.name).where(
                WebhookPartner.id.in_(ids), WebhookPartner.tenant_id == self._tenant_id()
            )
        )
        return {row.id: row.name for row in result.all()}

    async def create_webhook_partner(self, cmd: CreateWebhookPartnerCmd) -> UUID:
        partner_id = uuid.uuid4()
        record = WebhookPartner(
            id=partner_id,
            tenant_id=self._tenant_id(),
            name=cmd.name,
            url=cmd.url,
            auth_header_vault_ref=cmd.auth_header_vault_ref,
            active=True,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def create_inbound_route(self, cmd: CreateInboundRouteCmd) -> UUID:
        tenant_id = self._tenant_id()

        destinations = [
            d
            for d in (cmd.webhook_partner_id, cmd.as2_partner_id, cmd.sftp_partner_id)
            if d is not None
        ]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (webhook, as2, or sftp) must be provided")

        # Validate target UUIDs belong to this tenant
        if cmd.webhook_partner_id:
            result = await self.session.execute(
                select(WebhookPartner.id).where(
                    WebhookPartner.id == cmd.webhook_partner_id,
                    WebhookPartner.tenant_id == tenant_id,
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"Webhook partner {cmd.webhook_partner_id} not found or does not belong to this tenant"
                )

        if cmd.as2_partner_id:
            result = await self.session.execute(
                select(DataPlaneAS2Partner.id).where(
                    DataPlaneAS2Partner.id == cmd.as2_partner_id,
                    DataPlaneAS2Partner.tenant_id == tenant_id,
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"AS2 partner {cmd.as2_partner_id} not found or does not belong to this tenant"
                )

        if cmd.sftp_partner_id:
            result = await self.session.execute(
                select(SFTPPartner.id).where(
                    SFTPPartner.id == cmd.sftp_partner_id, SFTPPartner.tenant_id == tenant_id
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"SFTP partner {cmd.sftp_partner_id} not found or does not belong to this tenant"
                )

        route_id = uuid.uuid4()
        record = InboundRoute(
            id=route_id,
            tenant_id=tenant_id,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            transaction_type=cmd.transaction_type,
            webhook_partner_id=cmd.webhook_partner_id,
            as2_partner_id=cmd.as2_partner_id,
            sftp_partner_id=cmd.sftp_partner_id,
        )
        self.session.add(record)
        await self.session.flush()
        return route_id

    async def create_outbound_route(self, cmd: CreateOutboundRouteCmd) -> UUID:
        tenant_id = self._tenant_id()

        destinations = [d for d in (cmd.as2_partner_id, cmd.sftp_partner_id) if d is not None]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (as2 or sftp) must be provided")

        # Validate target UUIDs belong to this tenant
        if cmd.as2_partner_id:
            result = await self.session.execute(
                select(DataPlaneAS2Partner.id).where(
                    DataPlaneAS2Partner.id == cmd.as2_partner_id,
                    DataPlaneAS2Partner.tenant_id == tenant_id,
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"AS2 partner {cmd.as2_partner_id} not found or does not belong to this tenant"
                )

        if cmd.sftp_partner_id:
            result = await self.session.execute(
                select(SFTPPartner.id).where(
                    SFTPPartner.id == cmd.sftp_partner_id, SFTPPartner.tenant_id == tenant_id
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"SFTP partner {cmd.sftp_partner_id} not found or does not belong to this tenant"
                )

        route_id = uuid.uuid4()
        record = OutboundRoute(
            id=route_id,
            tenant_id=tenant_id,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            transaction_type=cmd.transaction_type,
            as2_partner_id=cmd.as2_partner_id,
            sftp_partner_id=cmd.sftp_partner_id,
        )
        self.session.add(record)
        await self.session.flush()
        return route_id

    async def get_all_routes(self) -> dict[str, list[Any]]:
        tenant_id = self._tenant_id()
        inbound_result = await self.session.execute(
            select(InboundRoute).where(InboundRoute.tenant_id == tenant_id)
        )
        outbound_result = await self.session.execute(
            select(OutboundRoute).where(OutboundRoute.tenant_id == tenant_id)
        )

        inbound_routes = list(inbound_result.scalars().all())
        outbound_routes = list(outbound_result.scalars().all())

        return {"inbound": inbound_routes, "outbound": outbound_routes}


class SqlAlchemyTenantRepository(TenantRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_tenant_flags(self, tenant_id: int) -> dict[str, Any] | None:
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant:
            return {"allow_private_as2": tenant.allow_private_as2}
        return None
