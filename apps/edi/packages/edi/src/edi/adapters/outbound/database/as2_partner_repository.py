import dataclasses
from collections.abc import Sequence
from typing import Any

from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, or_, select

from database.exceptions import DuplicateEntityError
from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import AS2Partner
from edi.domain.exceptions import PartnerAlreadyExistsError, PartnerInUseError
from edi.domain.models.as2 import AS2PartnerDomainModel
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort


class SqlAlchemyAS2TradingPartnerRepository(
    AS2TradingPartnerRepositoryPort, GlobalSqlAlchemyRepository
):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def save(self, aggregate: AS2PartnerDomainModel) -> None:
        tid_str = aggregate.tenant_id
        conds = [AS2Partner.id == aggregate.id]
        if tid_str == PLATFORM_TENANT_ID:
            conds.append(
                or_(AS2Partner.tenant_id == PLATFORM_TENANT_ID, AS2Partner.tenant_id.is_(None))
            )
        else:
            conds.append(AS2Partner.tenant_id == tid_str)

        result = await self.session.execute(select(AS2Partner).where(*conds))
        record = result.scalar_one_or_none()

        if record is None:
            record = AS2Partner(id=aggregate.id)
            self.session.add(record)

        for field in dataclasses.fields(aggregate):
            if field.name not in ("created_at", "updated_at", "_domain_events"):
                setattr(record, field.name, getattr(aggregate, field.name))

        self._drain_events(aggregate)

        try:
            await self.flush()
        except DuplicateEntityError as e:
            if e.constraint_name and "uq_tenant_as2_id" in e.constraint_name:
                raise PartnerAlreadyExistsError(
                    as2_id=str(aggregate.as2_id),
                    tenant_id=aggregate.tenant_id or PLATFORM_TENANT_ID,
                ) from e
            raise

    async def get_as2_partner(
        self, tenant_id: str, partner_id: str
    ) -> AS2PartnerDomainModel | None:
        tid_str = tenant_id
        result = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.id == partner_id,
                or_(
                    AS2Partner.tenant_id == tid_str,
                    AS2Partner.tenant_id == PLATFORM_TENANT_ID,
                    AS2Partner.tenant_id.is_(None),
                ),
            )
        )
        record = result.scalar_one_or_none()
        return (
            AS2PartnerDomainModel(
                **{
                    f.name: getattr(record, f.name)
                    for f in dataclasses.fields(AS2PartnerDomainModel)
                }
            )
            if record
            else None
        )

    async def is_vault_ref_in_use(self, vault_ref: str) -> bool:
        stmt = select(AS2Partner).where(
            or_(
                AS2Partner.private_key_vault_ref == vault_ref,
                AS2Partner.prev_private_key_vault_ref == vault_ref,
            )
        )
        res = await self.session.execute(stmt)
        return res.scalars().first() is not None

    async def get_as2_partner_for_write(self, tenant_id: str, partner_id: str) -> Any:
        tid_str = tenant_id
        conds = [AS2Partner.id == partner_id]
        if tid_str == PLATFORM_TENANT_ID:
            conds.append(
                or_(AS2Partner.tenant_id == PLATFORM_TENANT_ID, AS2Partner.tenant_id.is_(None))
            )
        else:
            conds.append(AS2Partner.tenant_id == tid_str)
        result = await self.session.execute(select(AS2Partner).where(*conds))
        return result.scalar_one_or_none()

    async def list_as2_partners(self, tenant_id: str) -> Sequence[AS2PartnerDomainModel]:
        tid_str = tenant_id
        if tid_str == PLATFORM_TENANT_ID:
            where_clause = or_(
                AS2Partner.tenant_id == PLATFORM_TENANT_ID, AS2Partner.tenant_id.is_(None)
            )
        else:
            where_clause = AS2Partner.tenant_id == tid_str
        result = await self.session.execute(select(AS2Partner).where(where_clause))
        return [
            AS2PartnerDomainModel(
                **{f.name: getattr(r, f.name) for f in dataclasses.fields(AS2PartnerDomainModel)}
            )
            for r in result.scalars().all()
        ]

    async def delete(self, aggregate: AS2PartnerDomainModel) -> None:
        tid_str = aggregate.tenant_id
        conds = [AS2Partner.id == aggregate.id]
        if tid_str == PLATFORM_TENANT_ID:
            conds.append(
                or_(AS2Partner.tenant_id == PLATFORM_TENANT_ID, AS2Partner.tenant_id.is_(None))
            )
        else:
            conds.append(AS2Partner.tenant_id == tid_str)
        from database.exceptions import ForeignKeyViolationError
        from database.interceptors import intercept_db_errors

        try:
            async with self.session.begin_nested(), intercept_db_errors():
                await self.session.execute(delete(AS2Partner).where(*conds))

                self._drain_events(aggregate)

                await self.session.flush()
        except ForeignKeyViolationError as e:
            raise PartnerInUseError(
                partner_id=str(aggregate.id), tenant_id=aggregate.tenant_id or PLATFORM_TENANT_ID
            ) from e

    async def get_as2_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        tid_str = tenant_id
        result = await self.session.execute(
            select(AS2Partner.id, AS2Partner.name).where(
                AS2Partner.id.in_(ids),
                or_(
                    AS2Partner.tenant_id == tid_str,
                    AS2Partner.tenant_id == PLATFORM_TENANT_ID,
                    AS2Partner.tenant_id.is_(None),
                ),
            )
        )
        return {row.id: row.name for row in result.all()}
