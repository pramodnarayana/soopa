import contextlib
import typing

import structlog

from ucp.ports.outbound.identity_provider_port import IdentityProviderPort
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort
from ucp.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

logger = structlog.get_logger(__name__)


class StateConflictError(Exception):
    """Raised when a resource is not in the expected state for an operation."""


class IdentitySyncService:
    """
    Pure business logic for synchronizing UCP domains (Tenants, Users)
    to an external Identity Provider (e.g. Zitadel).
    """

    def __init__(
        self,
        identity_provider: IdentityProviderPort,
        user_identity_provider: UserIdentityProviderPort,
        uow_factory: "typing.Callable[[], contextlib.AbstractAsyncContextManager[UcpUnitOfWorkPort]] | None" = None,
    ):
        self.identity_provider = identity_provider
        self.user_identity_provider = user_identity_provider
        self.uow_factory = uow_factory

    async def _resolve_idp_tenant_id(self, tenant_id: str) -> str:
        """
        Resolves the IDP tenant ID for the given platform tenant ID.
        Raises StateConflictError if the tenant is not provisioned.
        """
        if self.uow_factory is None:
            raise ValueError("uow_factory is required to resolve tenant IDs")

        assert self.uow_factory is not None
        async with self.uow_factory() as uow:
            tenant = await uow.tenant_repo.find_by_id(tenant_id)
            if not tenant or not tenant.idp_tenant_id:
                raise StateConflictError(
                    f"Tenant {tenant_id} is not fully provisioned in Identity Provider yet"
                )
            return tenant.idp_tenant_id

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
        self, user_id: str, tenant_id: str, email: str, first_name: str, last_name: str, role: str
    ) -> None:
        """
        Synchronizes a newly created UCP user to the Identity Provider.
        Creates the user and assigns the given role.
        """
        bound_logger = logger.bind(user_id=user_id, tenant_id=tenant_id, role=role)
        bound_logger.info("syncing_new_user_to_identity_provider", action="create")
        try:
            idp_tenant_id = await self._resolve_idp_tenant_id(tenant_id)

            idp_user_id = await self.user_identity_provider.create_user(
                org_id=idp_tenant_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
            )
            bound_logger.info("identity_sync_create_user_successful", idp_user_id=idp_user_id)

            await self.user_identity_provider.assign_tenant_role(
                user_id=idp_user_id, org_id=idp_tenant_id, role=role
            )
            bound_logger.info(
                "identity_sync_assign_role_successful", idp_user_id=idp_user_id, role=role
            )

            # Update the local database with the newly generated idp_user_id
            assert self.uow_factory is not None
            async with self.uow_factory() as uow:
                local_user = await uow.user_repo.find_by_id(user_id)
                if local_user:
                    local_user.idp_user_id = idp_user_id
                    await uow.user_repo.save(local_user)
                    await uow.commit()
                    bound_logger.info("identity_sync_updated_local_idp_user_id_successful")
                else:
                    bound_logger.warning("identity_sync_local_user_not_found_for_update")

        except Exception:
            bound_logger.exception("identity_sync_new_user_failed")
            raise

    async def handle_user_role_assigned(self, idp_user_id: str, tenant_id: str, role: str) -> None:
        """
        Synchronizes a role assignment to the Identity Provider.
        """
        bound_logger = logger.bind(idp_user_id=idp_user_id, tenant_id=tenant_id, role=role)
        bound_logger.info("syncing_user_role_assigned_to_identity_provider")

        try:
            idp_tenant_id = await self._resolve_idp_tenant_id(tenant_id)

            await self.user_identity_provider.assign_tenant_role(
                user_id=idp_user_id, org_id=idp_tenant_id, role=role
            )
            bound_logger.info("identity_sync_assign_role_successful")
        except Exception:
            bound_logger.exception("identity_sync_assign_role_failed")
            raise

    async def handle_user_updated(
        self, idp_user_id: str, tenant_id: str, first_name: str, last_name: str, role: str
    ) -> None:
        """
        Synchronizes profile and role updates to the Identity Provider.
        """
        bound_logger = logger.bind(idp_user_id=idp_user_id, tenant_id=tenant_id)
        bound_logger.info("syncing_user_update_to_identity_provider", action="update")
        try:
            idp_tenant_id = await self._resolve_idp_tenant_id(tenant_id)

            await self.user_identity_provider.update_user_profile(
                user_id=idp_user_id,
                org_id=idp_tenant_id,
                first_name=first_name,
                last_name=last_name,
            )
            bound_logger.debug("identity_sync_update_profile_successful")

            await self.user_identity_provider.update_tenant_role(
                user_id=idp_user_id, org_id=idp_tenant_id, role=role
            )
            bound_logger.debug("identity_sync_update_role_successful", role=role)
        except Exception:
            bound_logger.exception("identity_sync_user_update_failed")
            raise

    async def handle_user_status_toggled(
        self, idp_user_id: str, tenant_id: str, action: str
    ) -> None:
        """
        Activates or deactivates a user in the Identity Provider.
        """
        bound_logger = logger.bind(idp_user_id=idp_user_id, tenant_id=tenant_id, action=action)
        bound_logger.info("syncing_user_status_toggle_to_identity_provider")
        try:
            idp_tenant_id = await self._resolve_idp_tenant_id(tenant_id)

            if action not in ("activate", "deactivate"):
                raise ValueError(f"Invalid action for toggle user status: {action}")

            from typing import Literal

            valid_action: Literal["activate", "deactivate"] = (
                "activate" if action == "activate" else "deactivate"
            )

            await self.user_identity_provider.toggle_user_status(
                user_id=idp_user_id,
                org_id=idp_tenant_id,
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
