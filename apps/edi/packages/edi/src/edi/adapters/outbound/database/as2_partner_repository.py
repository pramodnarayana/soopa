import dataclasses
from collections.abc import Sequence
from typing import Any

from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, or_, select

from database.exceptions import DuplicateEntityError
from database.repository import BaseSqlAlchemyRepository
from edi.adapters.outbound.database.base_repository import GlobalSession
from edi.adapters.outbound.database.models.control_plane import AS2Partner
from edi.application.dto import (
    CreateAS2TradingPartnerCmd,
    UpdateAS2TradingPartnerCmd,
)
from edi.domain.exceptions import PartnerAlreadyExistsError, PartnerInUseError
from edi.domain.models import (
    AS2PartnerDomainModel,
)
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort


class SqlAlchemyAS2TradingPartnerRepository(
    AS2TradingPartnerRepositoryPort, BaseSqlAlchemyRepository
):
    def __init__(self, session: GlobalSession) -> None:
        BaseSqlAlchemyRepository.__init__(self, session)

    async def create_as2_identity(self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd) -> str:
        tid_str = tenant_id
        record = AS2Partner(
            tenant_id=tid_str,
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

        try:
            await self.flush()
        except DuplicateEntityError as e:
            if e.constraint_name and "uq_tenant_as2_id" in e.constraint_name:
                raise PartnerAlreadyExistsError(as2_id=cmd.as2_id, tenant_id=tenant_id) from e
            raise

        return record.id

    async def update_as2_identity(
        self, tenant_id: str, partner_id: str, cmd: UpdateAS2TradingPartnerCmd
    ) -> None:
        partner = await self.get_as2_partner_for_write(tenant_id, partner_id)
        if partner:
            import dataclasses

            for field in dataclasses.fields(cmd):
                value = getattr(cmd, field.name)
                if value is not None:
                    setattr(partner, field.name, value)

            try:
                await self.flush()
            except DuplicateEntityError as e:
                if e.constraint_name and "uq_tenant_as2_id" in e.constraint_name:
                    from edi.application.dto import UnsetType

                    as2_id_val = (
                        cmd.as2_id
                        if not isinstance(cmd.as2_id, UnsetType) and cmd.as2_id
                        else partner.as2_id
                    )
                    raise PartnerAlreadyExistsError(
                        as2_id=str(as2_id_val), tenant_id=tenant_id
                    ) from e
                raise

    async def rotate_as2_certificates(
        self,
        tenant_id: str,
        partner_id: str,
        new_public_cert: str,
        new_private_key_vault_ref: str | None,
    ) -> None:
        partner = await self.get_as2_partner_for_write(tenant_id, partner_id)
        if not partner:
            raise ValueError(f"AS2 Partner {partner_id} not found or access denied.")

        partner.prev_public_cert_pem = partner.public_cert_pem
        partner.prev_private_key_vault_ref = partner.private_key_vault_ref

        partner.public_cert_pem = new_public_cert
        if new_private_key_vault_ref is not None:
            partner.private_key_vault_ref = new_private_key_vault_ref

        await self.flush()

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

    async def delete_as2_identity(self, tenant_id: str, partner_id: str) -> None:
        tid_str = tenant_id
        conds = [AS2Partner.id == partner_id]
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
                await self.session.flush()
        except ForeignKeyViolationError as e:
            raise PartnerInUseError(partner_id=partner_id, tenant_id=tenant_id) from e

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
