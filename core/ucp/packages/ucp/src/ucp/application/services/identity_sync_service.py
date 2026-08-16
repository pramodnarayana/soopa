import structlog

from ...ports.identity_provider import IdentityProviderPort
from ...ports.outbound.user_identity_provider import IUserIdentityProvider

logger = structlog.get_logger(__name__)


class IdentitySyncService:
    """
    Pure business logic for synchronizing UCP domains (Tenants, Users)
    to an external Identity Provider (e.g. Zitadel).
    """

    def __init__(
        self,
        identity_provider: IdentityProviderPort,
        user_identity_provider: IUserIdentityProvider,
    ):
        self.identity_provider = identity_provider
        self.user_identity_provider = user_identity_provider

    async def handle_tenant_provisioned(self, tenant_id: str) -> None:
        """
        Synchronizes a newly provisioned tenant to the Identity Provider.
        """
        bound_logger = logger.bind(tenant_id=tenant_id)
        bound_logger.info("syncing_tenant_to_identity_provider", tenant_id=tenant_id)
        try:
            await self.identity_provider.sync_tenant(tenant_id)
            bound_logger.info("identity_sync_tenant_successful", tenant_id=tenant_id)
        except Exception:
            bound_logger.exception("identity_sync_tenant_failed", tenant_id=tenant_id)
            raise

    async def handle_user_created(
        self, org_id: str, email: str, first_name: str, last_name: str, role: str
    ) -> None:
        """
        Synchronizes a newly created UCP user to the Identity Provider.
        Creates the user and assigns the given role.
        """
        bound_logger = logger.bind(org_id=org_id, email=email, role=role)
        bound_logger.info("syncing_new_user_to_identity_provider", action="create")
        try:
            user_id = await self.user_identity_provider.create_user(
                org_id=org_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            bound_logger.info("identity_sync_create_user_successful", idp_user_id=user_id)

            await self.user_identity_provider.assign_tenant_role(
                user_id=user_id, org_id=org_id, role=role
            )
            bound_logger.info(
                "identity_sync_assign_role_successful", idp_user_id=user_id, role=role
            )
        except Exception:
            bound_logger.exception("identity_sync_new_user_failed")
            raise

    async def handle_user_updated(
        self, idp_user_id: str, org_id: str, first_name: str, last_name: str, role: str
    ) -> None:
        """
        Synchronizes profile and role updates to the Identity Provider.
        """
        bound_logger = logger.bind(idp_user_id=idp_user_id, org_id=org_id)
        bound_logger.info("syncing_user_update_to_identity_provider", action="update")
        try:
            await self.user_identity_provider.update_user_profile(
                user_id=idp_user_id,
                org_id=org_id,
                first_name=first_name,
                last_name=last_name,
            )
            bound_logger.debug("identity_sync_update_profile_successful")

            await self.user_identity_provider.update_tenant_role(
                user_id=idp_user_id, org_id=org_id, role=role
            )
            bound_logger.debug("identity_sync_update_role_successful", role=role)
        except Exception:
            bound_logger.exception("identity_sync_user_update_failed")
            raise

    async def handle_user_status_toggled(self, idp_user_id: str, org_id: str, action: str) -> None:
        """
        Activates or deactivates a user in the Identity Provider.
        """
        bound_logger = logger.bind(idp_user_id=idp_user_id, org_id=org_id, action=action)
        bound_logger.info("syncing_user_status_toggle_to_identity_provider")
        try:
            if action not in ("activate", "deactivate"):
                raise ValueError(f"Invalid action for toggle user status: {action}")

            from typing import Literal

            valid_action: Literal["activate", "deactivate"] = (
                "activate" if action == "activate" else "deactivate"
            )

            await self.user_identity_provider.toggle_user_status(
                user_id=idp_user_id,
                org_id=org_id,
                action=valid_action,
            )
            bound_logger.info("identity_sync_status_toggle_successful")
        except Exception:
            bound_logger.exception("identity_sync_status_toggle_failed")
            raise

    async def handle_user_deleted(self, idp_user_id: str) -> None:
        """
        Deletes a user from the Identity Provider.
        """
        bound_logger = logger.bind(idp_user_id=idp_user_id)
        bound_logger.info("syncing_user_deletion_to_identity_provider", action="delete")
        try:
            await self.user_identity_provider.delete_user(user_id=idp_user_id)
            bound_logger.info("identity_sync_user_deletion_successful")
        except Exception:
            bound_logger.exception("identity_sync_user_deletion_failed")
            raise
