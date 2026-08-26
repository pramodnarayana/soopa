import contextlib
import typing

import structlog
from platform_orm.models.identity import Tenant as DbTenant
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity_worker.domain.exceptions import IdentityProviderPortError
from identity_worker.ports.outbound.identity_provider_port import IdentityProviderPort
from identity_worker.ports.outbound.organization_provider_port import OrganizationProviderPort

logger = structlog.get_logger(__name__)


class ZitadelIdentityProviderPort(IdentityProviderPort):
    def __init__(
        self,
        org_provider: OrganizationProviderPort,
        session_factory: typing.Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]],
    ):
        self.org_provider = org_provider
        self.session_factory = session_factory

    async def sync_tenant(self, tenant_id: str) -> None:
        async with self.session_factory() as session:
            stmt = select(DbTenant).where(DbTenant.id == tenant_id)
            result = await session.execute(stmt)
            tenant = result.scalar_one_or_none()
            if not tenant:
                logger.warning("tenant_not_found_for_sync", tenant_id=tenant_id)
                return

            if tenant.idp_tenant_id:
                logger.info("tenant_already_synced", tenant_id=tenant_id)
                return

            try:
                org_id, grant_succeeded = await self.org_provider.create_organization(tenant.name)
            except IdentityProviderPortError as e:
                if e.status_code == 409:
                    logger.warning(
                        "organization_already_exists_in_idp",
                        tenant_id=tenant_id,
                    )
                raise

            if not grant_succeeded:
                raise IdentityProviderPortError(
                    "Organization was created but its project grant could not be assigned"
                )

            tenant.idp_tenant_id = org_id
            await session.commit()
            logger.info("tenant_synced_to_idp_successfully", tenant_id=tenant_id, org_id=org_id)
