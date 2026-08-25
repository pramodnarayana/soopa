from typing import Literal

import structlog

from identity_worker.ports.outbound.identity_provider_port import IdentityProviderPort

logger = structlog.get_logger(__name__)


class DummyIdentityProviderPort(IdentityProviderPort):
    """
    A stub Identity Provider that simulates syncing without actual external calls.
    Used for local development or when Zitadel is not configured.
    """

    async def sync_tenant(self, tenant_id: str) -> None:
        logger.info("dummy_idp_sync_tenant", tenant_id=tenant_id)

    async def create_user(
        self,
        org_id: str,
        email: str,
        first_name: str,
        last_name: str,
    ) -> str:
        return "dummy_user_id"

    async def assign_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        pass

    async def update_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        pass

    async def remove_tenant_role(self, user_id: str, org_id: str) -> None:
        pass

    async def update_user_profile(
        self,
        user_id: str,
        org_id: str,
        first_name: str,
        last_name: str,
    ) -> None:
        pass

    async def delete_user(self, user_id: str) -> None:
        pass

    async def toggle_user_status(
        self,
        user_id: str,
        org_id: str,
        action: Literal["activate", "deactivate"],
    ) -> None:
        pass
