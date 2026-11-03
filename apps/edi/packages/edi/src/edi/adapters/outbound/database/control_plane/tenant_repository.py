from sqlalchemy import select

from database.models.identity import Tenant
from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.domain.authorization.tenant import TenantFeatureFlags, TenantSummary
from edi.ports.outbound.tenant_repository import TenantRepositoryPort


class SqlAlchemyTenantRepository(TenantRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    @staticmethod
    def _to_domain_model(tenant: Tenant) -> TenantSummary:
        return TenantSummary(
            id=tenant.id,
            idp_tenant_id=tenant.idp_tenant_id,
            name=tenant.name,
        )

    async def get_tenant_flags(self, tenant_id: str) -> TenantFeatureFlags | None:
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None

        return TenantFeatureFlags(allow_private_as2=False)

    async def get_tenant(self, tenant_id: str) -> TenantSummary | None:
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None

        return self._to_domain_model(tenant)
