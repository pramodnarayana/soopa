from collections.abc import Sequence
from uuid import UUID

from api.domain.models import CreateOutboundEdiHeaderCmd, UpdateOutboundEdiHeaderCmd
from api.ports.edi_header_repository import EdiHeaderRepositoryPort
from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import OutboundEdiHeader
from domain.models import OutboundEdiHeaderDomainModel
from sqlalchemy import delete, select, update


class SqlAlchemyEdiHeaderRepository(EdiHeaderRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def create_outbound_edi_header(
        self, tenant_id: int, cmd: CreateOutboundEdiHeaderCmd
    ) -> UUID:
        import uuid

        header_id = uuid.uuid4()
        import dataclasses

        header = OutboundEdiHeader(id=header_id, tenant_id=tenant_id, **dataclasses.asdict(cmd))
        self.session.add(header)
        await self.session.flush()
        return header_id

    async def update_outbound_edi_header(
        self, tenant_id: int, header_id: UUID, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool:
        import dataclasses

        from api.domain.models import UNSET

        values = {k: v for k, v in dataclasses.asdict(cmd).items() if v is not UNSET}

        stmt = (
            update(OutboundEdiHeader)
            .where(
                OutboundEdiHeader.id == header_id,
                OutboundEdiHeader.tenant_id == tenant_id,
            )
            .values(**values)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def delete_outbound_edi_header(self, tenant_id: int, header_id: UUID) -> bool:
        stmt = delete(OutboundEdiHeader).where(
            OutboundEdiHeader.id == header_id,
            OutboundEdiHeader.tenant_id == tenant_id,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def get_outbound_edi_headers(
        self, tenant_id: int
    ) -> Sequence[OutboundEdiHeaderDomainModel]:
        stmt = select(OutboundEdiHeader).where(OutboundEdiHeader.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return [OutboundEdiHeaderDomainModel.model_validate(r) for r in result.scalars().all()]

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: int, trading_partner_id: str
    ) -> OutboundEdiHeaderDomainModel | None:
        stmt = select(OutboundEdiHeader).where(
            OutboundEdiHeader.tenant_id == tenant_id,
            OutboundEdiHeader.trading_partner_id == trading_partner_id,
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        return OutboundEdiHeaderDomainModel.model_validate(record) if record else None
