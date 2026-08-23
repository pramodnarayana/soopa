from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import OutboundEdiHeader
from edi.application.dto import (
    CreateOutboundEdiHeaderCmd,
    UpdateOutboundEdiHeaderCmd,
)
from edi.domain.models import (
    OutboundEdiHeaderDomainModel,
)
from edi.ports.outbound.edi_header_repository import EdiHeaderRepositoryPort


class SqlAlchemyEdiHeaderRepository(EdiHeaderRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def create_outbound_edi_header(
        self, tenant_id: str, cmd: CreateOutboundEdiHeaderCmd
    ) -> str:
        import dataclasses

        tid_str = tenant_id
        header = OutboundEdiHeader(tenant_id=tid_str, **dataclasses.asdict(cmd))
        self.session.add(header)
        await self.session.flush()
        return header.id

    async def update_outbound_edi_header(
        self, tenant_id: str, header_id: str, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool:
        import dataclasses

        from edi.application.dto import UnsetType

        tid_str = tenant_id
        values = {k: v for k, v in dataclasses.asdict(cmd).items() if not isinstance(v, UnsetType)}

        if not values:
            return True

        stmt = (
            update(OutboundEdiHeader)
            .where(
                OutboundEdiHeader.id == header_id,
                OutboundEdiHeader.tenant_id == tid_str,
                OutboundEdiHeader.deleted_at.is_(None),
            )
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def delete_outbound_edi_header(self, tenant_id: str, header_id: str) -> bool:
        tid_str = tenant_id
        stmt = (
            update(OutboundEdiHeader)
            .where(
                OutboundEdiHeader.id == header_id,
                OutboundEdiHeader.tenant_id == tid_str,
                OutboundEdiHeader.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def get_outbound_edi_headers(
        self, tenant_id: str
    ) -> Sequence[OutboundEdiHeaderDomainModel]:
        tid_str = tenant_id
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tid_str, OutboundEdiHeader.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return [
            OutboundEdiHeaderDomainModel(
                **{
                    k: v
                    for k, v in r.__dict__.items()
                    if not k.startswith("_") and k not in ("deleted_at", "deleted_by")
                }
            )
            for r in result.scalars().all()
        ]

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundEdiHeaderDomainModel | None:
        tid_str = tenant_id
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tid_str,
            OutboundEdiHeader.trading_partner_id == trading_partner_id,
            OutboundEdiHeader.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        return (
            OutboundEdiHeaderDomainModel(
                **{
                    k: v
                    for k, v in record.__dict__.items()
                    if not k.startswith("_") and k not in ("deleted_at", "deleted_by")
                }
            )
            if record
            else None
        )
