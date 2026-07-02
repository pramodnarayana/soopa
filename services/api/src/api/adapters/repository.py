import uuid
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from api.domain.models import (
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookPartnerCmd,
    UpdateAS2PartnershipCmd,
    UpdateAS2TradingPartnerCmd,
    UpdateSFTPPartnerCmd,
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
from sqlalchemy import delete, select
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
            url=cmd.url,
            public_cert_pem=cmd.public_cert_pem,
            public_cert_vault_ref=cmd.public_cert_vault_ref,
            private_key_vault_ref=cmd.private_key_vault_ref,
            active=False,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def update_as2_identity(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateAS2TradingPartnerCmd
    ) -> None:
        partner = await self.get_as2_partner(tenant_id, partner_id)
        if partner:
            if cmd.name is not None:
                partner.name = cmd.name
            if cmd.as2_id is not None:
                partner.as2_id = cmd.as2_id
            if cmd.is_local is not None:
                partner.is_local = cmd.is_local
            if cmd.url is not None:
                partner.url = cmd.url
            if cmd.public_cert_pem is not None:
                partner.public_cert_pem = cmd.public_cert_pem
            if cmd.public_cert_vault_ref is not None:
                partner.public_cert_vault_ref = cmd.public_cert_vault_ref
            if cmd.private_key_vault_ref is not None:
                partner.private_key_vault_ref = cmd.private_key_vault_ref
            if cmd.active is not None:
                partner.active = cmd.active
        await self.session.flush()

    async def get_as2_partner(self, tenant_id: int, partner_id: UUID) -> Any:
        result = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.id == partner_id,
                AS2Partner.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_as2_partners(self, tenant_id: int) -> Sequence[Any]:
        result = await self.session.execute(
            select(AS2Partner).where(AS2Partner.tenant_id == tenant_id)
        )
        return result.scalars().all()

    async def delete_as2_identity(self, tenant_id: int, partner_id: UUID) -> None:
        await self.session.execute(
            delete(AS2Partner).where(AS2Partner.id == partner_id, AS2Partner.tenant_id == tenant_id)
        )
        await self.session.flush()

    async def create_as2_partnership(self, tenant_id: int, cmd: CreateAS2PartnershipCmd) -> UUID:
        partnership_id = uuid.uuid4()
        record = AS2Partnership(
            id=partnership_id,
            tenant_id=tenant_id,
            name=cmd.name,
            local_partner_id=cmd.local_partner_id,
            remote_partner_id=cmd.remote_partner_id,
            credentials_vault_ref=cmd.credentials_vault_ref,
            mdn_type=cmd.mdn_type,
            mdn_url=cmd.mdn_url,
            encryption_algorithm=cmd.encryption_algorithm,
            signature_algorithm=cmd.signature_algorithm,
            edi_version=cmd.edi_version,
            advanced_flags=cmd.advanced_flags,
            active=False,
        )
        self.session.add(record)
        await self.session.flush()

        await self.create_outbox_event(
            tenant_id=tenant_id,
            event_type="AS2_PARTNERSHIP_CREATED",
            payload={"partnership_id": str(partnership_id), "tenant_id": tenant_id},
        )

        return partnership_id

    async def update_as2_partnership(
        self, tenant_id: int, partnership_id: UUID, cmd: UpdateAS2PartnershipCmd
    ) -> None:
        from api.domain.models import UNSET

        partnership = await self.get_as2_partnership(tenant_id, partnership_id)
        if partnership:
            if cmd.name is not UNSET:
                partnership.name = cmd.name
            if cmd.local_partner_id is not UNSET:
                partnership.local_partner_id = cmd.local_partner_id
            if cmd.remote_partner_id is not UNSET:
                partnership.remote_partner_id = cmd.remote_partner_id
            if cmd.credentials_vault_ref is not UNSET:
                partnership.credentials_vault_ref = cmd.credentials_vault_ref
            if cmd.mdn_type is not UNSET:
                partnership.mdn_type = cmd.mdn_type
            if cmd.mdn_url is not UNSET:
                partnership.mdn_url = cmd.mdn_url
            if cmd.encryption_algorithm is not UNSET:
                partnership.encryption_algorithm = cmd.encryption_algorithm
            if cmd.signature_algorithm is not UNSET:
                partnership.signature_algorithm = cmd.signature_algorithm
            if cmd.edi_version is not UNSET:
                partnership.edi_version = cmd.edi_version
            if cmd.advanced_flags is not UNSET:
                partnership.advanced_flags = cmd.advanced_flags
            if cmd.active is not UNSET:
                partnership.active = cmd.active
        await self.session.flush()

    async def delete_as2_partnership(self, tenant_id: int, partnership_id: UUID) -> None:
        await self.session.execute(
            delete(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tenant_id
            )
        )
        await self.session.flush()

    async def get_as2_partnership(self, tenant_id: int, partnership_id: UUID) -> Any:
        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()

    async def get_as2_partners_by_ids(self, ids: list[UUID], tenant_id: int) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(AS2Partner.id, AS2Partner.name).where(
                AS2Partner.id.in_(ids),
                AS2Partner.tenant_id == tenant_id,
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
            active=False,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def get_sftp_partner(self, partner_id: UUID) -> SFTPPartner | None:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id == partner_id, SFTPPartner.tenant_id == self._tenant_id()
            )
        )
        return result.scalar_one_or_none()

    async def list_sftp_partners(self) -> Sequence[Any]:
        result = await self.session.execute(
            select(SFTPPartner).where(SFTPPartner.tenant_id == self._tenant_id())
        )
        return result.scalars().all()

    async def update_sftp_partner(self, partner_id: UUID, cmd: UpdateSFTPPartnerCmd) -> None:
        partner = await self.get_sftp_partner(partner_id)
        if partner:
            if cmd.name is not None:
                partner.name = cmd.name
            if cmd.host is not None:
                partner.host = cmd.host
            if cmd.port is not None:
                partner.port = cmd.port
            if cmd.username is not None:
                partner.username = cmd.username
            if cmd.remote_path is not None:
                partner.remote_path = cmd.remote_path
            if cmd.credentials_vault_ref is not None:
                partner.credentials_vault_ref = cmd.credentials_vault_ref
        await self.session.flush()

    async def delete_sftp_partner(self, partner_id: UUID) -> None:
        await self.session.execute(
            delete(SFTPPartner).where(
                SFTPPartner.id == partner_id, SFTPPartner.tenant_id == self._tenant_id()
            )
        )
        await self.session.flush()

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

    async def get_webhook_partner(self, partner_id: UUID) -> Any:
        result = await self.session.execute(
            select(WebhookPartner).where(
                WebhookPartner.id == partner_id, WebhookPartner.tenant_id == self._tenant_id()
            )
        )
        return result.scalar_one_or_none()

    async def list_webhook_partners(self) -> Sequence[Any]:
        result = await self.session.execute(
            select(WebhookPartner).where(WebhookPartner.tenant_id == self._tenant_id())
        )
        return result.scalars().all()

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
            active=False,
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
