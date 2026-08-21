import structlog

from ucp.ports.outbound.identity_provider import IdentityProviderPortPort

logger = structlog.get_logger(__name__)


class DummyIdentityProviderPort(IdentityProviderPortPort):
    """
    A stub Identity Provider that simulates syncing without actual external calls.
    Used for local development or when Zitadel is not configured.
    """

    async def sync_tenant(self, tenant_id: str) -> None:
        logger.info("dummy_idp_sync_tenant", tenant_id=tenant_id)
