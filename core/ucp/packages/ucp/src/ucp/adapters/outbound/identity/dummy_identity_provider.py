import logging

from ucp.ports.identity_provider import IdentityProviderPort

logger = logging.getLogger(__name__)


class DummyIdentityProvider(IdentityProviderPort):
    """
    A stub Identity Provider that simulates syncing without actual external calls.
    Used for local development or when Zitadel is not configured.
    """

    async def sync_tenant(self, tenant_id: str) -> None:
        logger.info(
            f"[DummyIdentityProvider] Pretending to sync tenant {tenant_id} to external IDP"
        )
