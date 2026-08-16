from datetime import UTC, datetime

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import (
    AS2Partner,
    InboundRoute,
    SFTPPartner,
)
from domain.models import InboundRouteDomainModel
from identity.domain.identity_context import PLATFORM_TENANT_ID
from platform_orm.models import Webhook
from sqlalchemy import or_, select, update

from edi.domain.models import (
    CreateInboundRouteCmd,
    UnsetType,
    UpdateInboundRouteCmd,
)
from edi.ports.inbound_route_repository import InboundRouteRepositoryPort


class SqlAlchemyInboundRouteRepository(InboundRouteRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    # ------------------------------------------------------------------------
    # Routes (Now in Control Plane)
    # ------------------------------------------------------------------------
    async def _validate_inbound_destination(
        self, tenant_id: str, webhook_id: str | None, as2_id: str | None, sftp_id: str | None
    ) -> None:
        destinations = [d for d in (webhook_id, as2_id, sftp_id) if d is not None]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (webhook, as2, or sftp) must be provided")

        if webhook_id:
            result = await self.session.execute(
                select(Webhook.id).where(
                    Webhook.id == webhook_id,
                    Webhook.tenant_id == tenant_id,
                    Webhook.deleted_at.is_(None),
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"Webhook partner {webhook_id} not found or does not belong to this tenant"
                )

        if as2_id:
            result = await self.session.execute(
                select(AS2Partner.id).where(
                    AS2Partner.id == as2_id,
                    AS2Partner.tenant_id.in_([tenant_id, PLATFORM_TENANT_ID]),
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"AS2 partner {as2_id} not found or does not belong to this tenant"
                )

        if sftp_id:
            result = await self.session.execute(
                select(SFTPPartner.id).where(
                    SFTPPartner.id == sftp_id,
                    SFTPPartner.tenant_id == tenant_id,
                    SFTPPartner.deleted_at.is_(None),
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"SFTP partner {sftp_id} not found or does not belong to this tenant"
                )

    async def create_inbound_route(self, tenant_id: str, cmd: CreateInboundRouteCmd) -> str:
        await self._validate_inbound_destination(
            tenant_id, cmd.webhook_id, cmd.as2_partner_id, cmd.sftp_partner_id
        )

        record = InboundRoute(
            tenant_id=tenant_id,
            name=cmd.name,
            trading_partner_id=cmd.trading_partner_id,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            gs_sender_id=cmd.gs_sender_id,
            gs_receiver_id=cmd.gs_receiver_id,
            transaction_type=cmd.transaction_type,
            webhook_id=cmd.webhook_id,
            as2_partner_id=cmd.as2_partner_id,
            sftp_partner_id=cmd.sftp_partner_id,
            processing_mode=cmd.processing_mode,
        )
        self.session.add(record)
        await self.session.flush()
        return record.id

    async def update_inbound_route(
        self, tenant_id: str, route_id: str, cmd: UpdateInboundRouteCmd
    ) -> bool:
        result = await self.session.execute(
            select(InboundRoute).where(
                InboundRoute.id == route_id,
                InboundRoute.tenant_id == tenant_id,
                InboundRoute.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return False
        if not isinstance(cmd.name, UnsetType):
            record.name = cmd.name
        if not isinstance(cmd.trading_partner_id, UnsetType):
            record.trading_partner_id = cmd.trading_partner_id
        if not isinstance(cmd.isa_sender_id, UnsetType):
            record.isa_sender_id = cmd.isa_sender_id
        if not isinstance(cmd.isa_receiver_id, UnsetType):
            record.isa_receiver_id = cmd.isa_receiver_id
        if not isinstance(cmd.gs_sender_id, UnsetType):
            record.gs_sender_id = cmd.gs_sender_id
        if not isinstance(cmd.gs_receiver_id, UnsetType):
            record.gs_receiver_id = cmd.gs_receiver_id
        if not isinstance(cmd.transaction_type, UnsetType):
            record.transaction_type = cmd.transaction_type
        if not isinstance(cmd.processing_mode, UnsetType):
            record.processing_mode = cmd.processing_mode
        if not isinstance(cmd.webhook_id, UnsetType):
            record.webhook_id = cmd.webhook_id
        if not isinstance(cmd.as2_partner_id, UnsetType):
            record.as2_partner_id = cmd.as2_partner_id
        if not isinstance(cmd.sftp_partner_id, UnsetType):
            record.sftp_partner_id = cmd.sftp_partner_id
        if not isinstance(cmd.active, UnsetType):
            record.active = cmd.active

        await self._validate_inbound_destination(
            tenant_id,
            record.webhook_id,
            record.as2_partner_id,
            record.sftp_partner_id,
        )

        await self.session.flush()
        return True

    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: str,
        transaction_type: str | None = None,
    ) -> InboundRouteDomainModel | None:
        stmt = select(InboundRoute).where(
            InboundRoute.isa_sender_id == isa_sender_id,
            InboundRoute.isa_receiver_id == isa_receiver_id,
            InboundRoute.tenant_id == tenant_id,
            InboundRoute.deleted_at.is_(None),
        )
        if transaction_type:
            stmt = stmt.where(
                or_(
                    InboundRoute.transaction_type == transaction_type,
                    InboundRoute.transaction_type.is_(None),
                )
            ).order_by(InboundRoute.transaction_type.desc().nullslast())
        else:
            stmt = stmt.where(InboundRoute.transaction_type.is_(None)).order_by(InboundRoute.id)

        result = await self.session.execute(stmt)
        record = result.scalars().first()
        return InboundRouteDomainModel.model_validate(record) if record else None

    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteDomainModel]:
        result = await self.session.execute(
            select(InboundRoute).where(
                InboundRoute.tenant_id == tenant_id, InboundRoute.deleted_at.is_(None)
            )
        )
        return [InboundRouteDomainModel.model_validate(r) for r in result.scalars().all()]

    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> str | None:
        result = await self.session.execute(
            select(InboundRoute.tenant_id).where(
                InboundRoute.isa_sender_id == isa_sender_id,
                InboundRoute.isa_receiver_id == isa_receiver_id,
                InboundRoute.active.is_(True),
                InboundRoute.deleted_at.is_(None),
            )
        )
        rows = result.scalars().all()
        unique_tenants = set(rows)
        if len(unique_tenants) > 1:
            raise ValueError(
                f"Ambiguous ISA pair ({isa_sender_id!r} -> {isa_receiver_id!r}) "
                f"matched {len(unique_tenants)} distinct tenants: {unique_tenants}"
            )
        return str(rows[0]) if rows else None

    async def delete_inbound_route(self, tenant_id: str, route_id: str) -> bool:
        result = await self.session.execute(
            update(InboundRoute)
            .where(
                InboundRoute.id == route_id,
                InboundRoute.tenant_id == tenant_id,
                InboundRoute.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None), active=False)
        )
        await self.session.flush()
        return bool(getattr(result, "rowcount", 0) > 0)
