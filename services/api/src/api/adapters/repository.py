import uuid
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from api.domain.models import (
    UNSET,
    CreateAS2PartnershipCmd,
    CreateAS2TradingPartnerCmd,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    CreateSFTPPartnerCmd,
    CreateWebhookCmd,
    UnsetType,
    UpdateAS2PartnershipCmd,
    UpdateAS2TradingPartnerCmd,
    UpdateInboundRouteCmd,
    UpdateOutboundRouteCmd,
    UpdateSFTPPartnerCmd,
)
from api.ports.repository import (
    ControlPlaneRepositoryPort,
    DataPlaneRepositoryPort,
    TenantRepositoryPort,
)
from database.encryption import db_encryption
from database.models.control_plane import (
    AS2Partner,
    AS2Partnership,
    InboundRoute,
    OutboundRoute,
    SFTPPartner,
    Tenant,
    Webhook,
)
from database.models.control_plane import Outbox as GlobalOutbox
from database.models.data_plane import EdiMessage
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyControlPlaneRepository(ControlPlaneRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[Any, Any, Any] | None:
        from database.repository import PartnershipRepository

        repo = PartnershipRepository(self.session)
        return await repo.get_partnership_by_as2_ids(as2_from, as2_to)

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
            mdn_type=cmd.mdn_type,
            mdn_url=cmd.mdn_url,
            encryption_algorithm=cmd.encryption_algorithm,
            signature_algorithm=cmd.signature_algorithm,
            active=False,
        )
        self.session.add(record)
        await self.session.flush()
        return partnership_id

    async def update_as2_partnership(
        self, tenant_id: int, partnership_id: UUID, cmd: UpdateAS2PartnershipCmd
    ) -> None:
        partnership = await self.get_as2_partnership(tenant_id, partnership_id)
        if partnership:
            if not isinstance(cmd.local_partner_id, UnsetType):
                if cmd.local_partner_id is not None:
                    r = await self.session.execute(
                        select(AS2Partner.id).where(
                            AS2Partner.id == cmd.local_partner_id,
                            AS2Partner.tenant_id.in_([tenant_id, 0]),
                        )
                    )
                    if not r.scalar_one_or_none():
                        raise ValueError("Local AS2 partner not found")
                partnership.local_partner_id = cmd.local_partner_id
            if not isinstance(cmd.remote_partner_id, UnsetType):
                if cmd.remote_partner_id is not None:
                    r = await self.session.execute(
                        select(AS2Partner.id).where(
                            AS2Partner.id == cmd.remote_partner_id,
                            AS2Partner.tenant_id.in_([tenant_id, 0]),
                        )
                    )
                    if not r.scalar_one_or_none():
                        raise ValueError("Remote AS2 partner not found")
                partnership.remote_partner_id = cmd.remote_partner_id
            if cmd.name is not UNSET:
                partnership.name = cmd.name
            if cmd.mdn_type is not UNSET:
                partnership.mdn_type = cmd.mdn_type
            if cmd.mdn_url is not UNSET:
                partnership.mdn_url = cmd.mdn_url
            if cmd.encryption_algorithm is not UNSET:
                partnership.encryption_algorithm = cmd.encryption_algorithm
            if cmd.signature_algorithm is not UNSET:
                partnership.signature_algorithm = cmd.signature_algorithm

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

    async def get_as2_partners_by_ids(self, tenant_id: int, ids: list[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(AS2Partner.id, AS2Partner.name).where(
                AS2Partner.id.in_(ids),
                AS2Partner.tenant_id.in_([tenant_id, 0]),
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

    # ------------------------------------------------------------------------
    # SFTP Partners (Now in Control Plane)
    # ------------------------------------------------------------------------
    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> UUID:
        partner_id = uuid.uuid4()
        record = SFTPPartner(
            id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            host=cmd.host,
            port=cmd.port,
            username=cmd.username,
            inbound_remote_path=cmd.inbound_remote_path
            if hasattr(cmd, "inbound_remote_path")
            else None,
            outbound_remote_path=cmd.outbound_remote_path
            if hasattr(cmd, "outbound_remote_path")
            else None,
            password_encrypted=db_encryption.encrypt(cmd.password) if cmd.password else None,
            credentials_vault_ref=cmd.credentials_vault_ref,
            host_key=cmd.host_key,
            active=False,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def get_sftp_partner(self, tenant_id: int, partner_id: UUID) -> Any:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id == partner_id, SFTPPartner.tenant_id == tenant_id
            )
        )
        return result.scalar_one_or_none()

    async def list_sftp_partners(self, tenant_id: int) -> Sequence[Any]:
        result = await self.session.execute(
            select(SFTPPartner).where(SFTPPartner.tenant_id == tenant_id)
        )
        return result.scalars().all()

    async def update_sftp_partner(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateSFTPPartnerCmd
    ) -> None:
        partner = await self.get_sftp_partner(tenant_id, partner_id)
        if partner:
            if cmd.name is not None:
                partner.name = cmd.name
            if cmd.host is not None:
                partner.host = cmd.host
            if cmd.port is not None:
                partner.port = cmd.port
            if cmd.username is not None:
                partner.username = cmd.username
            if hasattr(cmd, "inbound_remote_path") and cmd.inbound_remote_path is not None:
                partner.inbound_remote_path = cmd.inbound_remote_path
            if hasattr(cmd, "outbound_remote_path") and cmd.outbound_remote_path is not None:
                partner.outbound_remote_path = cmd.outbound_remote_path
            if cmd.password is not None:
                partner.password_encrypted = (
                    db_encryption.encrypt(cmd.password) if cmd.password else None
                )
            if cmd.credentials_vault_ref is not None:
                partner.credentials_vault_ref = cmd.credentials_vault_ref
            if cmd.host_key is not None:
                partner.host_key = cmd.host_key
            if cmd.active is not None:
                partner.active = cmd.active
        await self.session.flush()

    async def delete_sftp_partner(self, tenant_id: int, partner_id: UUID) -> None:
        await self.session.execute(
            delete(SFTPPartner).where(
                SFTPPartner.id == partner_id, SFTPPartner.tenant_id == tenant_id
            )
        )
        await self.session.flush()

    async def get_sftp_partners_by_ids(self, tenant_id: int, ids: list[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(SFTPPartner.id, SFTPPartner.name).where(
                SFTPPartner.id.in_(ids), SFTPPartner.tenant_id == tenant_id
            )
        )
        return {row.id: row.name for row in result.all()}

    # ------------------------------------------------------------------------
    # Webhook Partners (Now in Control Plane)
    # ------------------------------------------------------------------------
    async def create_webhook(self, tenant_id: int, cmd: CreateWebhookCmd) -> UUID:
        partner_id = uuid.uuid4()
        record = Webhook(
            id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            url=cmd.url,
            auth_header_vault_ref=cmd.auth_header_vault_ref,
            active=True,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def get_webhook(self, tenant_id: int, partner_id: UUID) -> Any:
        result = await self.session.execute(
            select(Webhook).where(Webhook.id == partner_id, Webhook.tenant_id == tenant_id)
        )
        return result.scalar_one_or_none()

    async def list_webhooks(self, tenant_id: int) -> Sequence[Any]:
        result = await self.session.execute(select(Webhook).where(Webhook.tenant_id == tenant_id))
        return result.scalars().all()

    async def get_webhooks_by_ids(self, tenant_id: int, ids: list[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(Webhook.id, Webhook.name).where(
                Webhook.id.in_(ids), Webhook.tenant_id == tenant_id
            )
        )
        return {row.id: row.name for row in result.all()}

    # ------------------------------------------------------------------------
    # Routes (Now in Control Plane)
    # ------------------------------------------------------------------------
    async def create_inbound_route(self, tenant_id: int, cmd: CreateInboundRouteCmd) -> UUID:
        destinations = [
            d for d in (cmd.webhook_id, cmd.as2_partner_id, cmd.sftp_partner_id) if d is not None
        ]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (webhook, as2, or sftp) must be provided")

        if cmd.webhook_id:
            result = await self.session.execute(
                select(Webhook.id).where(
                    Webhook.id == cmd.webhook_id,
                    Webhook.tenant_id == tenant_id,
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"Webhook partner {cmd.webhook_id} not found or does not belong to this tenant"
                )

        if cmd.as2_partner_id:
            result = await self.session.execute(
                select(AS2Partner.id).where(
                    AS2Partner.id == cmd.as2_partner_id,
                    AS2Partner.tenant_id.in_([tenant_id, 0]),
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
            name=cmd.name,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            transaction_type=cmd.transaction_type,
            webhook_id=cmd.webhook_id,
            as2_partner_id=cmd.as2_partner_id,
            sftp_partner_id=cmd.sftp_partner_id,
            processing_mode=cmd.processing_mode,
        )
        self.session.add(record)
        await self.session.flush()
        return route_id

    async def update_inbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateInboundRouteCmd
    ) -> bool:
        result = await self.session.execute(
            select(InboundRoute).where(
                InboundRoute.id == route_id, InboundRoute.tenant_id == tenant_id
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return False
        if not isinstance(cmd.name, UnsetType):
            record.name = cmd.name
        if not isinstance(cmd.isa_sender_id, UnsetType):
            record.isa_sender_id = cmd.isa_sender_id
        if not isinstance(cmd.isa_receiver_id, UnsetType):
            record.isa_receiver_id = cmd.isa_receiver_id
        if not isinstance(cmd.transaction_type, UnsetType):
            record.transaction_type = cmd.transaction_type
        if not isinstance(cmd.processing_mode, UnsetType):
            record.processing_mode = cmd.processing_mode
        if not isinstance(cmd.webhook_id, UnsetType):
            if cmd.webhook_id is not None:
                r = await self.session.execute(
                    select(Webhook.id).where(
                        Webhook.id == cmd.webhook_id, Webhook.tenant_id == tenant_id
                    )
                )
                if not r.scalar_one_or_none():
                    raise ValueError("Webhook partner not found")
            record.webhook_id = cmd.webhook_id
        if not isinstance(cmd.as2_partner_id, UnsetType):
            if cmd.as2_partner_id is not None:
                r = await self.session.execute(
                    select(AS2Partner.id).where(
                        AS2Partner.id == cmd.as2_partner_id,
                        AS2Partner.tenant_id.in_([tenant_id, 0]),
                    )
                )
                if not r.scalar_one_or_none():
                    raise ValueError("AS2 partner not found")
            record.as2_partner_id = cmd.as2_partner_id
        if not isinstance(cmd.sftp_partner_id, UnsetType):
            if cmd.sftp_partner_id is not None:
                r = await self.session.execute(
                    select(SFTPPartner.id).where(
                        SFTPPartner.id == cmd.sftp_partner_id, SFTPPartner.tenant_id == tenant_id
                    )
                )
                if not r.scalar_one_or_none():
                    raise ValueError("SFTP partner not found")
            record.sftp_partner_id = cmd.sftp_partner_id
        if not isinstance(cmd.active, UnsetType):
            record.active = cmd.active

        destinations = [
            d
            for d in (record.webhook_id, record.as2_partner_id, record.sftp_partner_id)
            if d is not None
        ]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination must be provided")

        await self.session.flush()
        return True

    async def delete_inbound_route(self, tenant_id: int, route_id: UUID) -> bool:
        result = await self.session.execute(
            delete(InboundRoute).where(
                InboundRoute.id == route_id, InboundRoute.tenant_id == tenant_id
            )
        )
        await self.session.flush()
        return bool(getattr(result, "rowcount", 0) > 0)

    async def create_outbound_route(self, tenant_id: int, cmd: CreateOutboundRouteCmd) -> UUID:
        destinations = [d for d in (cmd.as2_partner_id, cmd.sftp_partner_id) if d is not None]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (as2 or sftp) must be provided")

        if cmd.as2_partner_id:
            result = await self.session.execute(
                select(AS2Partner.id).where(
                    AS2Partner.id == cmd.as2_partner_id,
                    AS2Partner.tenant_id.in_([tenant_id, 0]),
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
            name=cmd.name,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            transaction_type=cmd.transaction_type,
            as2_partner_id=cmd.as2_partner_id,
            sftp_partner_id=cmd.sftp_partner_id,
            processing_mode=cmd.processing_mode,
        )
        self.session.add(record)
        await self.session.flush()
        return route_id

    async def update_outbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateOutboundRouteCmd
    ) -> bool:
        result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.id == route_id, OutboundRoute.tenant_id == tenant_id
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return False
        if not isinstance(cmd.name, UnsetType):
            record.name = cmd.name
        if not isinstance(cmd.isa_sender_id, UnsetType):
            record.isa_sender_id = cmd.isa_sender_id
        if not isinstance(cmd.isa_receiver_id, UnsetType):
            record.isa_receiver_id = cmd.isa_receiver_id
        if not isinstance(cmd.transaction_type, UnsetType):
            record.transaction_type = cmd.transaction_type
        if not isinstance(cmd.processing_mode, UnsetType):
            record.processing_mode = cmd.processing_mode
        if not isinstance(cmd.as2_partner_id, UnsetType):
            if cmd.as2_partner_id is not None:
                r = await self.session.execute(
                    select(AS2Partner.id).where(
                        AS2Partner.id == cmd.as2_partner_id,
                        AS2Partner.tenant_id.in_([tenant_id, 0]),
                    )
                )
                if not r.scalar_one_or_none():
                    raise ValueError("AS2 partner not found")
            record.as2_partner_id = cmd.as2_partner_id
        if not isinstance(cmd.sftp_partner_id, UnsetType):
            if cmd.sftp_partner_id is not None:
                r = await self.session.execute(
                    select(SFTPPartner.id).where(
                        SFTPPartner.id == cmd.sftp_partner_id, SFTPPartner.tenant_id == tenant_id
                    )
                )
                if not r.scalar_one_or_none():
                    raise ValueError("SFTP partner not found")
            record.sftp_partner_id = cmd.sftp_partner_id
        if not isinstance(cmd.active, UnsetType):
            record.active = cmd.active

        destinations = [d for d in (record.as2_partner_id, record.sftp_partner_id) if d is not None]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (as2 or sftp) must be provided")

        await self.session.flush()
        return True

    async def delete_outbound_route(self, tenant_id: int, route_id: UUID) -> bool:
        result = await self.session.execute(
            delete(OutboundRoute).where(
                OutboundRoute.id == route_id, OutboundRoute.tenant_id == tenant_id
            )
        )
        await self.session.flush()
        return bool(getattr(result, "rowcount", 0) > 0)

    async def get_all_routes(self, tenant_id: int) -> dict[str, list[Any]]:
        inbound_result = await self.session.execute(
            select(InboundRoute).where(InboundRoute.tenant_id == tenant_id)
        )
        outbound_result = await self.session.execute(
            select(OutboundRoute).where(OutboundRoute.tenant_id == tenant_id)
        )

        inbound_routes = list(inbound_result.scalars().all())
        outbound_routes = list(outbound_result.scalars().all())

        return {"inbound": inbound_routes, "outbound": outbound_routes}


class SqlAlchemyDataPlaneRepository(DataPlaneRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_edi_message(self, tenant_id: int, payload: dict[str, Any]) -> UUID:
        msg = EdiMessage(tenant_id=tenant_id, **payload)
        self.session.add(msg)
        await self.session.flush()
        return msg.id

    async def create_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> UUID:
        from database.models.data_plane import Outbox

        event_id = uuid.uuid4()
        record = Outbox(
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


class SqlAlchemyTenantRepository(TenantRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_tenant_flags(self, tenant_id: int) -> dict[str, Any] | None:
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant:
            return {"allow_private_as2": tenant.allow_private_as2}
        return None
