import structlog

from ucp.adapters.outbound.database.uow import SqlAlchemyUcpUnitOfWork
from ucp.bootstrap.container import _async_session_maker
from ucp.domain.exceptions import IdentityProviderPortError
from ucp.ports.outbound.identity_provider import IdentityProviderPortPort
from ucp.ports.outbound.organization_provider import IOrganizationProvider

logger = structlog.get_logger(__name__)


class ZitadelIdentityProviderPort(IdentityProviderPortPort):
    def __init__(self, org_provider: IOrganizationProvider):
        self.org_provider = org_provider

    async def sync_tenant(self, tenant_id: str) -> None:
        async with _async_session_maker() as session:
            uow = SqlAlchemyUcpUnitOfWork(session)
            async with uow:
                tenant = await uow.tenant_repo.find_by_id(tenant_id)
                if not tenant:
                    logger.warning("tenant_not_found_for_sync", tenant_id=tenant_id)
                    return

                if tenant.idp_tenant_id:
                    logger.info("tenant_already_synced", tenant_id=tenant_id)
                    return

                try:
                    org_id, _ = await self.org_provider.create_organization(tenant.name)
                except IdentityProviderPortError as e:
                    if e.status_code == 409:
                        logger.warning(
                            "organization_already_exists_in_idp",
                            tenant_id=tenant_id,
                        )
                    raise

                tenant.set_idp_tenant_id(org_id)
                await uow.tenant_repo.save(tenant)
                await uow.commit()
                logger.info("tenant_synced_to_idp_successfully", tenant_id=tenant_id, org_id=org_id)
