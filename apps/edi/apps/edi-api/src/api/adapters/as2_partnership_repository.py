import uuid
from uuid import UUID

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import AS2Partner, AS2Partnership
from domain.models import AS2PartnerDomainModel, AS2PartnershipDomainModel
from sqlalchemy import delete, select

from api.domain.models import CreateAS2PartnershipCmd, UnsetType, UpdateAS2PartnershipCmd
from api.ports.as2_partnership_repository import AS2PartnershipRepositoryPort


class SqlAlchemyAS2PartnershipRepository(AS2PartnershipRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel] | None:
        from database.repository import PartnershipRepository

        repo = PartnershipRepository(self.session)
        return await repo.get_partnership_by_as2_ids(as2_from, as2_to)

    # The following AS2Partnership methods remain under SqlAlchemyAS2PartnershipRepository which was defined above.
    # We will define a new class for Outbox below.

    async def create_as2_partnership(self, tenant_id: int, cmd: CreateAS2PartnershipCmd) -> UUID:
        tid_str = str(tenant_id) if tenant_id is not None else None
        local_r = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.id == cmd.local_partner_id,
                AS2Partner.tenant_id.in_([tid_str, "0"]),
            )
        )
        local_partner = local_r.scalar_one_or_none()

        remote_r = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.id == cmd.remote_partner_id,
                AS2Partner.tenant_id.in_([tid_str, "0"]),
            )
        )
        remote_partner = remote_r.scalar_one_or_none()

        if not local_partner or not remote_partner:
            raise ValueError("Local or Remote partner not found")

        partnership_id = uuid.uuid4()
        record = AS2Partnership(
            id=partnership_id,
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
        return partnership_id

    async def update_as2_partnership(
        self, tenant_id: int, partnership_id: UUID, cmd: UpdateAS2PartnershipCmd
    ) -> None:
        tid_str = str(tenant_id) if tenant_id is not None else None
        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tid_str
            )
        )
        partnership = result.scalar_one_or_none()
        if partnership:
            if not isinstance(cmd.local_partner_id, UnsetType):
                if cmd.local_partner_id is not None:
                    r = await self.session.execute(
                        select(AS2Partner.id).where(
                            AS2Partner.id == cmd.local_partner_id,
                            AS2Partner.tenant_id.in_([tid_str, "0"]),
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
                            AS2Partner.tenant_id.in_([tid_str, "0"]),
                        )
                    )
                    if not r.scalar_one_or_none():
                        raise ValueError("Remote AS2 partner not found")
                partnership.remote_partner_id = cmd.remote_partner_id
            import dataclasses

            for field in dataclasses.fields(cmd):
                # Skip partner IDs which have special logic
                if field.name in ("local_partner_id", "remote_partner_id"):
                    continue
                value = getattr(cmd, field.name)
                if not isinstance(value, UnsetType):
                    setattr(partnership, field.name, value)
        await self.session.flush()

    async def delete_as2_partnership(self, tenant_id: int, partnership_id: UUID) -> None:
        tid_str = str(tenant_id) if tenant_id is not None else None
        await self.session.execute(
            delete(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tid_str
            )
        )
        await self.session.flush()

    async def get_as2_partnership(
        self, tenant_id: int, partnership_id: UUID
    ) -> AS2PartnershipDomainModel | None:
        tid_str = str(tenant_id) if tenant_id is not None else None
        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tid_str
            )
        )
        record = result.scalar_one_or_none()
        return AS2PartnershipDomainModel.model_validate(record) if record else None

    async def get_as2_partners_by_ids(self, tenant_id: int, ids: list[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        tid_str = str(tenant_id) if tenant_id is not None else None
        result = await self.session.execute(
            select(AS2Partner.id, AS2Partner.name).where(
                AS2Partner.id.in_(ids),
                AS2Partner.tenant_id.in_([tid_str, "0"]),
            )
        )
        return {row.id: row.name for row in result.all()}
