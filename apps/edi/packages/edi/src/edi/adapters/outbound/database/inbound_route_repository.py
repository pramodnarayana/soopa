import dataclasses
from datetime import UTC, datetime
from uuid import UUID

from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import or_, select, update

from database.models import Webhook
from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partner,
    InboundRoute,
    SFTPPartner,
)
from edi.application.dto import UnsetType
from edi.domain.models.inbound_routes import InboundRouteDomainModel
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort


class SqlAlchemyInboundRouteRepository(InboundRouteRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    # ------------------------------------------------------------------------
    # Routes (Now in Control Plane)
    # ------------------------------------------------------------------------
    async def _validate_inbound_destination(
        self,
        tenant_id: str,
        webhook_id: str | UUID | UnsetType | None,
        as2_id: str | UUID | UnsetType | None,
        sftp_id: str | UUID | UnsetType | None,
    ) -> None:
        destinations = [
            d
            for d in (webhook_id, as2_id, sftp_id)
            if d is not None and not isinstance(d, UnsetType)
        ]
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
                    AS2Partner.active.is_(True),
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

    async def save(self, aggregate: InboundRouteDomainModel) -> None:
        await self._validate_inbound_destination(
            aggregate.tenant_id,
            aggregate.webhook_id,
            aggregate.as2_partner_id,
            aggregate.sftp_partner_id,
        )

        result = await self.session.execute(
            select(InboundRoute).where(
                InboundRoute.id == aggregate.id,
                InboundRoute.tenant_id == aggregate.tenant_id,
                InboundRoute.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            record = InboundRoute(id=aggregate.id)
            self.session.add(record)

        for field in dataclasses.fields(aggregate):
            if field.name not in ("created_at", "updated_at", "_domain_events"):
                setattr(record, field.name, getattr(aggregate, field.name))

        self._drain_events(aggregate)
        await self.session.flush()

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
        return (
            InboundRouteDomainModel(
                **{
                    f.name: getattr(record, f.name)
                    for f in dataclasses.fields(InboundRouteDomainModel)
                }
            )
            if record
            else None
        )

    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteDomainModel]:
        result = await self.session.execute(
            select(InboundRoute).where(
                InboundRoute.tenant_id == tenant_id, InboundRoute.deleted_at.is_(None)
            )
        )
        return [
            InboundRouteDomainModel(
                **{f.name: getattr(r, f.name) for f in dataclasses.fields(InboundRouteDomainModel)}
            )
            for r in result.scalars().all()
        ]

    async def get_inbound_route_by_id(
        self, tenant_id: str, route_id: str
    ) -> InboundRouteDomainModel | None:
        result = await self.session.execute(
            select(InboundRoute).where(
                InboundRoute.id == route_id,
                InboundRoute.tenant_id == tenant_id,
                InboundRoute.deleted_at.is_(None),
            )
        )
        record = result.scalars().first()
        return (
            InboundRouteDomainModel(
                **{
                    f.name: getattr(record, f.name)
                    for f in dataclasses.fields(InboundRouteDomainModel)
                }
            )
            if record
            else None
        )

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

    async def delete(self, aggregate: InboundRouteDomainModel) -> None:
        await self.session.execute(
            update(InboundRoute)
            .where(
                InboundRoute.id == aggregate.id,
                InboundRoute.tenant_id == aggregate.tenant_id,
                InboundRoute.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None), active=False)
        )

        self._drain_events(aggregate)
        await self.session.flush()
