from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, func, select
from sqlalchemy.orm import aliased

from database.exceptions import DuplicateEntityError
from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import AS2Partner as OrmAS2Partner
from edi.adapters.outbound.database.models.control_plane import AS2Partnership as OrmAS2Partnership
from edi.domain.exceptions import PartnershipAlreadyExistsError
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort


class SqlAlchemyAS2PartnershipRepository(AS2PartnershipRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    @staticmethod
    def _to_domain_model(record: OrmAS2Partnership) -> AS2Partnership:
        return AS2Partnership(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            local_partner_id=record.local_partner_id,
            remote_partner_id=record.remote_partner_id,
            mdn_type=record.mdn_type,
            encryption_algorithm=record.encryption_algorithm,
            signature_algorithm=record.signature_algorithm,
            created_at=record.created_at,
            updated_at=record.updated_at,
            credentials_vault_ref=record.credentials_vault_ref,
            mdn_url=record.mdn_url,
            advanced_flags=record.advanced_flags,
            active=record.active,
        )

    @staticmethod
    def _to_partner_domain_model(record: OrmAS2Partner) -> AS2Partner:
        return AS2Partner(
            id=record.id,
            tenant_id=record.tenant_id,
            as2_id=record.as2_id,
            name=record.name,
            is_local=record.is_local,
            created_at=record.created_at,
            updated_at=record.updated_at,
            public_cert_pem=record.public_cert_pem,
            public_cert_vault_ref=record.public_cert_vault_ref,
            private_key_vault_ref=record.private_key_vault_ref,
            prev_public_cert_pem=record.prev_public_cert_pem,
            prev_public_cert_vault_ref=record.prev_public_cert_vault_ref,
            prev_private_key_vault_ref=record.prev_private_key_vault_ref,
            url=record.url,
            active=record.active,
        )

    @staticmethod
    def _update_record_from_domain(record: OrmAS2Partnership, aggregate: AS2Partnership) -> None:
        record.tenant_id = aggregate.tenant_id or ""
        record.name = aggregate.name
        record.local_partner_id = aggregate.local_partner_id
        record.remote_partner_id = aggregate.remote_partner_id
        record.mdn_type = aggregate.mdn_type
        record.encryption_algorithm = aggregate.encryption_algorithm
        record.signature_algorithm = aggregate.signature_algorithm
        record.credentials_vault_ref = aggregate.credentials_vault_ref
        record.mdn_url = aggregate.mdn_url
        record.advanced_flags = aggregate.advanced_flags
        record.active = aggregate.active

    async def list_as2_partnerships(self, tenant_id: str | None) -> list[AS2Partnership]:
        normalized_tenant_id = tenant_id or PLATFORM_TENANT_ID
        result = await self.session.execute(
            select(OrmAS2Partnership).where(OrmAS2Partnership.tenant_id == normalized_tenant_id)
        )
        return [self._to_domain_model(r) for r in result.scalars().all()]

    async def get_as2_partnerships_by_remote_partner_id(
        self, tenant_id: str | None, remote_partner_id: str, active: bool | None = None
    ) -> list[AS2Partnership]:
        normalized_tenant_id = tenant_id or PLATFORM_TENANT_ID
        stmt = select(OrmAS2Partnership).where(
            OrmAS2Partnership.tenant_id == normalized_tenant_id,
            OrmAS2Partnership.remote_partner_id == remote_partner_id,
        )
        if active is not None:
            stmt = stmt.where(OrmAS2Partnership.active.is_(active))
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2Partnership, AS2Partner, AS2Partner] | None:

        LocalPartner = aliased(OrmAS2Partner)
        RemotePartner = aliased(OrmAS2Partner)

        stmt = (
            select(OrmAS2Partnership, LocalPartner, RemotePartner)
            .join(LocalPartner, OrmAS2Partnership.local_partner_id == LocalPartner.id)
            .join(RemotePartner, OrmAS2Partnership.remote_partner_id == RemotePartner.id)
            .where(
                OrmAS2Partnership.tenant_id == PLATFORM_TENANT_ID,
                func.lower(LocalPartner.as2_id) == as2_to.lower(),
                func.lower(RemotePartner.as2_id) == as2_from.lower(),
                OrmAS2Partnership.active.is_(True),
                LocalPartner.active.is_(True),
                RemotePartner.active.is_(True),
            )
        )

        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None

        partnership_orm, local_partner_orm, remote_partner_orm = row

        return (
            self._to_domain_model(partnership_orm),
            self._to_partner_domain_model(local_partner_orm),
            self._to_partner_domain_model(remote_partner_orm),
        )

    async def save(self, aggregate: AS2Partnership) -> None:
        normalized_tenant_id = aggregate.tenant_id or PLATFORM_TENANT_ID
        if normalized_tenant_id != PLATFORM_TENANT_ID:
            raise ValueError(
                f"AS2Partnership must be a global configuration. Expected tenant_id={PLATFORM_TENANT_ID}"
            )

        aggregate.tenant_id = normalized_tenant_id

        if aggregate.active:
            existing_active = await self.session.execute(
                select(OrmAS2Partnership).where(
                    OrmAS2Partnership.tenant_id == normalized_tenant_id,
                    OrmAS2Partnership.local_partner_id == aggregate.local_partner_id,
                    OrmAS2Partnership.remote_partner_id == aggregate.remote_partner_id,
                    OrmAS2Partnership.active.is_(True),
                    OrmAS2Partnership.id != aggregate.id,
                )
            )
            if existing_active.first():
                raise PartnershipAlreadyExistsError(
                    tenant_id=normalized_tenant_id,
                    local_partner_id=aggregate.local_partner_id,
                    remote_partner_id=aggregate.remote_partner_id,
                )

        result = await self.session.execute(
            select(OrmAS2Partnership).where(
                OrmAS2Partnership.id == aggregate.id,
                OrmAS2Partnership.tenant_id == normalized_tenant_id,
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            record = OrmAS2Partnership(id=aggregate.id)
            self.session.add(record)

        self._update_record_from_domain(record, aggregate)

        await self._drain_events(aggregate)
        try:
            await self.flush()
        except DuplicateEntityError as exc:
            raise PartnershipAlreadyExistsError(
                tenant_id=normalized_tenant_id,
                local_partner_id=aggregate.local_partner_id,
                remote_partner_id=aggregate.remote_partner_id,
            ) from exc

    async def delete(self, aggregate: AS2Partnership) -> None:
        normalized_tenant_id = aggregate.tenant_id or PLATFORM_TENANT_ID
        await self.session.execute(
            delete(OrmAS2Partnership).where(
                OrmAS2Partnership.id == aggregate.id,
                OrmAS2Partnership.tenant_id == normalized_tenant_id,
            )
        )
        await self._drain_events(aggregate)
        await self.flush()

    async def get_as2_partnership_by_identifiers(
        self, tenant_id: str | None, local_partner_id: str, remote_partner_id: str
    ) -> AS2Partnership | None:
        normalized_tenant_id = tenant_id or PLATFORM_TENANT_ID
        stmt = select(OrmAS2Partnership).where(
            OrmAS2Partnership.tenant_id == normalized_tenant_id,
            OrmAS2Partnership.local_partner_id == local_partner_id,
            OrmAS2Partnership.remote_partner_id == remote_partner_id,
        )
        record = (await self.session.execute(stmt)).scalar_one_or_none()
        if not record:
            return None
        return self._to_domain_model(record)

    async def get_as2_partnership(
        self, tenant_id: str | None, partnership_id: str
    ) -> AS2Partnership | None:
        normalized_tenant_id = tenant_id or PLATFORM_TENANT_ID
        result = await self.session.execute(
            select(OrmAS2Partnership).where(
                OrmAS2Partnership.id == partnership_id,
                OrmAS2Partnership.tenant_id == normalized_tenant_id,
            )
        )
        record = result.scalar_one_or_none()
        return self._to_domain_model(record) if record else None
