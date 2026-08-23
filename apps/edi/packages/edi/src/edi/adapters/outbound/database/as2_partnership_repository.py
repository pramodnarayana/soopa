from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, select

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import AS2Partner, AS2Partnership
from edi.application.dto import (
    CreateAS2PartnershipCmd,
    UnsetType,
    UpdateAS2PartnershipCmd,
)
from edi.domain.models import (
    AS2PartnerDomainModel,
    AS2PartnershipDomainModel,
)
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort


class SqlAlchemyAS2PartnershipRepository(AS2PartnershipRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def list_as2_partnerships(self, tenant_id: str) -> list[AS2PartnershipDomainModel]:
        result = await self.session.execute(
            select(AS2Partnership).where(AS2Partnership.tenant_id == tenant_id)
        )
        return [
            AS2PartnershipDomainModel(
                **{k: v for k, v in r.__dict__.items() if not k.startswith("_")}
            )
            for r in result.scalars().all()
        ]

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel] | None:
        from edi.adapters.outbound.database.repository import PartnershipRepository

        repo = PartnershipRepository(self.session)
        return await repo.get_partnership_by_as2_ids(as2_from, as2_to)

    async def create_as2_partnership(self, tenant_id: str, cmd: CreateAS2PartnershipCmd) -> str:
        tid_str = tenant_id
        local_r = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.id == cmd.local_partner_id,
                AS2Partner.tenant_id.in_([tid_str, PLATFORM_TENANT_ID]),
            )
        )
        local_partner = local_r.scalar_one_or_none()

        remote_r = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.id == cmd.remote_partner_id,
                AS2Partner.tenant_id.in_([tid_str, PLATFORM_TENANT_ID]),
            )
        )
        remote_partner = remote_r.scalar_one_or_none()

        if not local_partner or not remote_partner:
            raise ValueError("Local or Remote partner not found")

        record = AS2Partnership(
            tenant_id=tid_str,
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
        return record.id

    async def update_as2_partnership(
        self, tenant_id: str, partnership_id: str, cmd: UpdateAS2PartnershipCmd
    ) -> None:
        tid_str = tenant_id
        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tid_str
            )
        )
        partnership = result.scalar_one_or_none()
        if partnership:
            import dataclasses

            for field in dataclasses.fields(cmd):
                value = getattr(cmd, field.name)
                if not isinstance(value, UnsetType):
                    setattr(partnership, field.name, value)
        await self.session.flush()

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        tid_str = tenant_id
        await self.session.execute(
            delete(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tid_str
            )
        )
        await self.session.flush()

    async def get_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> AS2PartnershipDomainModel | None:
        tid_str = tenant_id
        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tid_str
            )
        )
        record = result.scalar_one_or_none()
        return (
            AS2PartnershipDomainModel(
                **{k: v for k, v in record.__dict__.items() if not k.startswith("_")}
            )
            if record
            else None
        )

    async def get_as2_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        tid_str = tenant_id
        result = await self.session.execute(
            select(AS2Partner.id, AS2Partner.name).where(
                AS2Partner.id.in_(ids),
                AS2Partner.tenant_id.in_([tid_str, PLATFORM_TENANT_ID]),
            )
        )
        return {row.id: row.name for row in result.all()}
