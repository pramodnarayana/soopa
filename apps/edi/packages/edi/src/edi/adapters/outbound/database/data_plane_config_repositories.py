from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.data_plane import (
    AS2Partner,
    AS2Partnership,
    InboundRoute,
    OutboundEdiHeader,
    OutboundRoute,
    SFTPPartner,
    Webhook,
)
from edi.domain.enums import EdiConnectionType
from edi.domain.models.as2 import AS2PartnerDomainModel, AS2PartnershipDomainModel
from edi.domain.models.base import ProcessingMode
from edi.domain.models.headers import OutboundEdiHeaderDomainModel
from edi.domain.models.inbound_routes import InboundRouteDomainModel
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.domain.models.sftp import SFTPPartnerDomainModel
from edi.domain.models.webhooks import WebhookDomainModel
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort


class ReadOnlyDataPlaneRepositoryError(Exception):
    pass


class SqlAlchemyDataPlaneInboundRouteRepository(InboundRouteRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: InboundRouteDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: InboundRouteDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: str,
        transaction_type: str | None = None,
    ) -> InboundRouteDomainModel | None:
        stmt = select(InboundRoute).where(
            InboundRoute.tenant_id == tenant_id,
            InboundRoute.isa_sender_id == isa_sender_id,
            InboundRoute.isa_receiver_id == isa_receiver_id,
        )
        if transaction_type:
            stmt = stmt.where(InboundRoute.transaction_type == transaction_type)
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_inbound_route_by_id(
        self, tenant_id: str, route_id: str
    ) -> InboundRouteDomainModel | None:
        stmt = select(InboundRoute).where(
            InboundRoute.tenant_id == tenant_id, InboundRoute.id == route_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> str | None:
        # Not applicable for a data plane scoped to a tenant
        raise ReadOnlyDataPlaneRepositoryError(
            "Cannot resolve tenant from tenant-scoped data plane"
        )

    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteDomainModel]:
        stmt = select(InboundRoute).where(InboundRoute.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: InboundRoute) -> InboundRouteDomainModel:
        return InboundRouteDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            isa_sender_id=record.isa_sender_id,
            isa_receiver_id=record.isa_receiver_id,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            trading_partner_id=record.trading_partner_id,
            gs_sender_id=record.gs_sender_id,
            gs_receiver_id=record.gs_receiver_id,
            transaction_type=record.transaction_type,
            processing_mode=ProcessingMode(record.processing_mode)
            if record.processing_mode
            else None,
            webhook_id=record.webhook_id,
            as2_partner_id=record.as2_partner_id,
            sftp_partner_id=record.sftp_partner_id,
            connection_type=EdiConnectionType(record.connection_type)
            if record.connection_type
            else None,
        )


class SqlAlchemyDataPlaneOutboundRouteRepository(OutboundRouteRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: OutboundRouteDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: OutboundRouteDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_outbound_route_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundRouteDomainModel | None:
        stmt = select(OutboundRoute).where(
            OutboundRoute.tenant_id == tenant_id,
            OutboundRoute.trading_partner_id == trading_partner_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_outbound_route(
        self, tenant_id: str, route_id: str
    ) -> OutboundRouteDomainModel | None:
        stmt = select(OutboundRoute).where(
            OutboundRoute.tenant_id == tenant_id, OutboundRoute.id == route_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def list_outbound_routes(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> Sequence[OutboundRouteDomainModel]:
        stmt = (
            select(OutboundRoute)
            .where(OutboundRoute.tenant_id == tenant_id)
            .limit(limit)
            .offset(offset)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: OutboundRoute) -> OutboundRouteDomainModel:
        return OutboundRouteDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            trading_partner_id=record.trading_partner_id,
            name=record.name,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            connection_type=EdiConnectionType(record.connection_type)
            if record.connection_type
            else None,
            as2_partner_id=record.as2_partner_id,
            sftp_partner_id=record.sftp_partner_id,
        )


class SqlAlchemyDataPlaneSFTPPartnerRepository(SFTPPartnerRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: SFTPPartnerDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: SFTPPartnerDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_sftp_partner(
        self, tenant_id: str, partner_id: str
    ) -> SFTPPartnerDomainModel | None:
        stmt = select(SFTPPartner).where(
            SFTPPartner.tenant_id == tenant_id, SFTPPartner.id == partner_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def list_sftp_partners(self, tenant_id: str) -> list[SFTPPartnerDomainModel]:
        stmt = select(SFTPPartner).where(SFTPPartner.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def get_sftp_partners_by_ids(
        self, tenant_id: str, partner_ids: list[str]
    ) -> list[SFTPPartnerDomainModel]:
        stmt = select(SFTPPartner).where(
            SFTPPartner.tenant_id == tenant_id, SFTPPartner.id.in_(partner_ids)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: SFTPPartner) -> SFTPPartnerDomainModel:
        return SFTPPartnerDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            host=record.host,
            port=record.port,
            username=record.username,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            host_key=record.host_key,
            inbound_remote_path=record.inbound_remote_path,
            outbound_remote_path=record.outbound_remote_path,
            password_encrypted=record.password_encrypted,
            credentials_vault_ref=record.credentials_vault_ref,
        )


class SqlAlchemyDataPlaneAS2PartnerRepository(AS2TradingPartnerRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: AS2PartnerDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: AS2PartnerDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_as2_partner(
        self, tenant_id: str, remote_partner_id: str
    ) -> AS2PartnerDomainModel | None:
        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == tenant_id, AS2Partner.id == remote_partner_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def list_as2_partners(self, tenant_id: str) -> list[AS2PartnerDomainModel]:
        stmt = select(AS2Partner).where(AS2Partner.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def get_as2_partners_by_ids(
        self, tenant_id: str, partner_ids: list[str]
    ) -> list[AS2PartnerDomainModel]:
        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == tenant_id, AS2Partner.id.in_(partner_ids)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def is_vault_ref_in_use(self, tenant_id: str, vault_ref: str) -> bool:
        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == tenant_id, AS2Partner.private_key_vault_ref == vault_ref
        )
        return (await self.session.execute(stmt)).scalars().first() is not None

    @staticmethod
    def _to_domain_model(record: AS2Partner) -> AS2PartnerDomainModel:
        return AS2PartnerDomainModel(
            id=record.id,
            as2_id=record.as2_id,
            name=record.name,
            is_local=record.is_local,
            created_at=record.created_at,
            updated_at=record.updated_at,
            tenant_id=record.tenant_id,
            public_cert_pem=record.public_cert_pem,
            public_cert_vault_ref=record.public_cert_vault_ref,
            private_key_vault_ref=record.private_key_vault_ref,
            prev_public_cert_pem=record.prev_public_cert_pem,
            prev_public_cert_vault_ref=record.prev_public_cert_vault_ref,
            prev_private_key_vault_ref=record.prev_private_key_vault_ref,
            url=record.url,
            active=record.active,
        )


class SqlAlchemyDataPlaneAS2PartnershipRepository(AS2PartnershipRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: AS2PartnershipDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: AS2PartnershipDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> AS2PartnershipDomainModel | None:
        stmt = select(AS2Partnership).where(
            AS2Partnership.tenant_id == tenant_id, AS2Partnership.id == partnership_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel] | None:
        return None

    async def get_as2_partnership_by_identifiers(
        self, tenant_id: str, local_partner_id: str, remote_partner_id: str
    ) -> AS2PartnershipDomainModel | None:
        stmt = select(AS2Partnership).where(
            AS2Partnership.tenant_id == tenant_id,
            AS2Partnership.local_partner_id == local_partner_id,
            AS2Partnership.remote_partner_id == remote_partner_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def list_as2_partnerships(self, tenant_id: str) -> list[AS2PartnershipDomainModel]:
        stmt = select(AS2Partnership).where(AS2Partnership.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: AS2Partnership) -> AS2PartnershipDomainModel:
        return AS2PartnershipDomainModel(
            id=record.id,
            name=record.name,
            local_partner_id=record.local_partner_id,
            remote_partner_id=record.remote_partner_id,
            mdn_type=record.mdn_type,
            encryption_algorithm=record.encryption_algorithm,
            signature_algorithm=record.signature_algorithm,
            created_at=record.created_at,
            updated_at=record.updated_at,
            tenant_id=record.tenant_id,
            credentials_vault_ref=record.credentials_vault_ref,
            mdn_url=record.mdn_url,
            advanced_flags=record.advanced_flags,
            active=record.active,
        )


class SqlAlchemyDataPlaneWebhookRepository(WebhookRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: WebhookDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: WebhookDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_webhook(self, tenant_id: str, webhook_id: str) -> WebhookDomainModel | None:
        stmt = select(Webhook).where(Webhook.tenant_id == tenant_id, Webhook.id == webhook_id)
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_webhooks_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> Sequence[WebhookDomainModel]:
        stmt = select(Webhook).where(Webhook.tenant_id == tenant_id).limit(limit).offset(offset)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def list_webhooks(self, tenant_id: str) -> Sequence[WebhookDomainModel]:
        return await self.get_webhooks_by_tenant(tenant_id)

    @staticmethod
    def _to_domain_model(record: Webhook) -> WebhookDomainModel:
        return WebhookDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            url=record.url,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            auth_header_vault_ref=record.auth_header_vault_ref,
        )


class SqlAlchemyDataPlaneEdiHeaderRepository(EdiHeaderRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: OutboundEdiHeaderDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: OutboundEdiHeaderDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_outbound_edi_header(
        self, tenant_id: str, header_id: str
    ) -> OutboundEdiHeaderDomainModel | None:
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tenant_id, OutboundEdiHeader.id == header_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundEdiHeaderDomainModel | None:
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tenant_id,
            OutboundEdiHeader.trading_partner_id == trading_partner_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_outbound_edi_headers(
        self, tenant_id: str
    ) -> Sequence[OutboundEdiHeaderDomainModel]:
        stmt = select(OutboundEdiHeader).where(OutboundEdiHeader.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: OutboundEdiHeader) -> OutboundEdiHeaderDomainModel:
        return OutboundEdiHeaderDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            trading_partner_id=record.trading_partner_id,
            isa_sender_id=record.isa_sender_id,
            isa_receiver_id=record.isa_receiver_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            name=record.name,
            isa_sender_qualifier=record.isa_sender_qualifier,
            isa_receiver_qualifier=record.isa_receiver_qualifier,
            gs_sender_id=record.gs_sender_id,
            gs_receiver_id=record.gs_receiver_id,
            transaction_type=record.transaction_type,
            default_standard=record.default_standard,
            default_version=record.default_version,
        )
