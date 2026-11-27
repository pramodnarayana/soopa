"""Provider-agnostic Identity Synchronization Service.

Synchronizes ONLY authentication identities (users + optional Enterprise dedicated
realms) to the configured IdP via the minimal 5-method `IdentityProviderAdminPort`.
Tenancy hierarchy, app subscriptions, and RBAC/PBAC/ReBAC roles are strictly owned
by the platform PostgreSQL database — zero vendor project/role sync bloat.
"""

from __future__ import annotations

import asyncio
import contextlib
import typing

import structlog
from identity.domain.constants import TenantIsolationMode
from identity.ports.outbound.identity_provider_admin_port import IdentityProviderAdminPort

from identity_worker.ports.outbound.identity_sync_repository_port import (
    IdentitySyncUnitOfWorkPort,
    SyncTenant,
)

logger = structlog.get_logger(__name__)


async def _complete_cleanup(cleanup: typing.Awaitable[object]) -> None:
    """Wait for cleanup to finish even if this task is cancelled again."""
    cleanup_task = asyncio.ensure_future(cleanup)
    while True:
        try:
            await asyncio.shield(cleanup_task)
            return
        except asyncio.CancelledError:
            if cleanup_task.done():
                cleanup_task.result()
                return


class StateConflictError(Exception):
    """Raised when a resource is not in the expected state for an operation."""


class IdentityProvisioningError(Exception):
    """Raised when the external IdP Admin API returns a structured failure Result."""


class IdentitySyncService:
    """Synchronizes users and dedicated enterprise realms via `IdentityProviderAdminPort`."""

    def __init__(
        self,
        idp_admin: IdentityProviderAdminPort,
        uow_factory: typing.Callable[
            [], contextlib.AbstractAsyncContextManager[IdentitySyncUnitOfWorkPort]
        ],
        *,
        default_global_realm: str = "soopa-global",
        default_user_password: str | None = None,
    ) -> None:
        self._idp_admin = idp_admin
        self.uow_factory = uow_factory
        self._default_global_realm = default_global_realm
        self._default_user_password = default_user_password

    def _extract_target_realm(self, tenant: SyncTenant) -> str:
        if tenant.idp_realm_name:
            return tenant.idp_realm_name
        if tenant.isolation_mode == TenantIsolationMode.DEDICATED_IDP_ORG.value:
            raise StateConflictError(
                f"Enterprise tenant {tenant.id} dedicated realm is not provisioned yet."
            )
        return self._default_global_realm

    async def _resolve_tenant_realm(self, tenant_id: str) -> str:
        async with self.uow_factory() as uow:
            tenant = await uow.repo.get_tenant(tenant_id)
            if tenant is None:
                raise StateConflictError(f"Tenant {tenant_id} does not exist.")
            return self._extract_target_realm(tenant)

    async def handle_tenant_provisioned(self, tenant_id: str) -> None:
        """Provision a dedicated IdP realm ONLY for Enterprise tenants; pooled tenants share global realm."""
        bound_logger = logger.bind(tenant_id=tenant_id)
        bound_logger.info("syncing_tenant_to_identity_provider")
        try:
            async with self.uow_factory() as uow:
                tenant = await uow.repo.get_tenant(tenant_id)
                if tenant is None:
                    bound_logger.info("tenant_not_found_for_sync_skipping")
                    return

                if tenant.idp_realm_name:
                    bound_logger.info("tenant_already_synced", realm=tenant.idp_realm_name)
                    return

                if tenant.isolation_mode == TenantIsolationMode.DEDICATED_IDP_ORG.value:
                    slug = tenant.slug or tenant.id
                    realm_res = await self._idp_admin.provision_dedicated_enterprise_realm(
                        slug=slug,
                        display_name=tenant.name,
                    )
                    if realm_res.is_err:
                        err = realm_res.unwrap_err()
                        bound_logger.error(
                            "identity_sync_dedicated_realm_failed",
                            code=err.code,
                            message=err.message,
                        )
                        raise IdentityProvisioningError(err.message)
                    realm_name = realm_res.unwrap().realm_name
                else:
                    # Pooled B2C Individuals & SMB Organizations share the single global realm
                    realm_name = self._default_global_realm

                await uow.repo.update_tenant_idp_realm(tenant_id, realm_name)
                await uow.commit()
                bound_logger.info(
                    "identity_sync_tenant_successful",
                    realm=realm_name,
                    isolation_mode=tenant.isolation_mode,
                )
        except Exception:
            bound_logger.exception("identity_sync_tenant_failed")
            raise

    async def handle_tenant_name_updated(self, tenant_id: str, new_name: str) -> None:
        logger.info(
            "tenant_name_updated_platform_owned_noop",
            tenant_id=tenant_id,
            new_name=new_name,
        )

    async def handle_tenant_status_toggled(self, tenant_id: str, active: bool) -> None:
        logger.info(
            "tenant_status_toggled_platform_owned_noop",
            tenant_id=tenant_id,
            active=active,
        )

    async def handle_tenant_deleted(self, tenant_id: str) -> None:
        logger.info("tenant_deleted_platform_owned_noop", tenant_id=tenant_id)

    async def handle_app_subscribed(self, tenant_id: str, idp_project_id: str | None) -> None:
        """App subscriptions are strictly owned by `ucp.app_subscriptions` (zero IdP grant sync)."""
        logger.info(
            "app_subscribed_platform_owned_noop",
            tenant_id=tenant_id,
            idp_project_id=idp_project_id,
        )

    async def handle_app_unsubscribed(self, tenant_id: str, idp_project_id: str | None) -> None:
        """App unsubscriptions are strictly owned by `ucp.app_subscriptions` (zero IdP revoke sync)."""
        logger.info(
            "app_unsubscribed_platform_owned_noop",
            tenant_id=tenant_id,
            idp_project_id=idp_project_id,
        )

    async def handle_user_created(
        self,
        user_id: str,
        tenant_id: str,
        email: str,
        first_name: str,
        last_name: str,
        role: str,
    ) -> None:
        """Provision the user in the target IdP realm and link `(idp_issuer, idp_subject) -> user_id`."""
        bound_logger = logger.bind(user_id=user_id, tenant_id=tenant_id, role=role)
        bound_logger.info("syncing_new_user_to_identity_provider", action="create")
        try:
            async with self.uow_factory() as uow:
                local_user = await uow.repo.get_user_for_update(user_id)
                if local_user is None:
                    bound_logger.info("identity_sync_local_user_not_found_for_update")
                    return

                tenant = await uow.repo.get_tenant(tenant_id)
                if tenant is None:
                    raise StateConflictError(f"Tenant {tenant_id} does not exist.")
                realm = self._extract_target_realm(tenant)

                if local_user.idp_user_id:
                    bound_logger.info(
                        "identity_sync_user_already_linked",
                        idp_user_id=local_user.idp_user_id,
                        realm=realm,
                    )
                    return

                display_name = f"{first_name} {last_name}".strip() or email
                await self._execute_user_create_with_compensation(
                    uow=uow,
                    local_user_id=user_id,
                    realm=realm,
                    email=email,
                    display_name=display_name,
                    bound_logger=bound_logger,
                )
        except Exception:
            bound_logger.exception("identity_sync_new_user_failed")
            raise

    async def _execute_user_create_with_compensation(
        self,
        *,
        uow: IdentitySyncUnitOfWorkPort,
        local_user_id: str,
        realm: str,
        email: str,
        display_name: str,
        bound_logger: structlog.stdlib.BoundLogger,
    ) -> None:
        created_subject: str | None = None
        did_create = False
        try:
            res = await self._idp_admin.create_user(
                realm=realm,
                email=email,
                display_name=display_name,
                initial_password=self._default_user_password,
            )
            if res.is_err:
                err = res.unwrap_err()
                bound_logger.error(
                    "identity_sync_create_user_idp_error",
                    code=err.code,
                    message=err.message,
                )
                raise IdentityProvisioningError(err.message)

            ext_ref = res.unwrap()
            created_subject = ext_ref.idp_subject
            did_create = ext_ref.created

            await uow.repo.update_user_idp_mapping(local_user_id, ext_ref.idp_subject)
            await uow.repo.upsert_external_identity(
                user_id=local_user_id,
                idp_issuer=ext_ref.idp_issuer,
                idp_subject=ext_ref.idp_subject,
                idp_realm_name=ext_ref.idp_realm_name,
            )
            await uow.commit()
            bound_logger.info(
                "identity_sync_user_created_and_linked",
                idp_issuer=ext_ref.idp_issuer,
                idp_subject=ext_ref.idp_subject,
                realm=ext_ref.idp_realm_name,
            )
        except BaseException:
            bound_logger.exception("identity_sync_user_create_compensating")
            try:
                await _complete_cleanup(uow.rollback())
            except Exception:
                bound_logger.exception("identity_sync_uow_rollback_failed")
            if created_subject and did_create:
                try:
                    await _complete_cleanup(
                        self._idp_admin.delete_user(realm=realm, external_subject=created_subject)
                    )
                except Exception:
                    bound_logger.exception(
                        "identity_sync_create_user_compensation_failed",
                        idp_subject=created_subject,
                    )
            raise

    async def handle_user_role_assigned(
        self,
        user_id: str,
        idp_user_id: str | None,
        tenant_id: str,
        role: str,
    ) -> None:
        """Roles & capabilities are strictly owned by `identity.user_roles` (zero IdP role push)."""
        logger.info(
            "user_role_assigned_platform_owned_noop",
            user_id=user_id,
            idp_user_id=idp_user_id,
            tenant_id=tenant_id,
            role=role,
        )

    async def handle_user_updated(
        self,
        idp_user_id: str,
        tenant_id: str,
        first_name: str,
        last_name: str,
        role: str,
    ) -> None:
        bound_logger = logger.bind(idp_user_id=idp_user_id, tenant_id=tenant_id, role=role)
        bound_logger.info("syncing_user_update_to_identity_provider", action="update")
        realm = await self._resolve_tenant_realm(tenant_id)
        display_name = f"{first_name} {last_name}".strip()
        res = await self._idp_admin.update_user(
            realm=realm,
            external_subject=idp_user_id,
            display_name=display_name or None,
        )
        if res.is_err:
            err = res.unwrap_err()
            bound_logger.error(
                "identity_sync_user_update_failed", code=err.code, message=err.message
            )
            raise IdentityProvisioningError(err.message)
        bound_logger.info("identity_sync_user_update_successful")

    async def handle_user_status_toggled(
        self,
        idp_user_id: str,
        tenant_id: str,
        action: str,
    ) -> None:
        bound_logger = logger.bind(idp_user_id=idp_user_id, tenant_id=tenant_id, action=action)
        bound_logger.info("syncing_user_status_toggle_to_identity_provider")
        if action not in ("activate", "deactivate"):
            raise ValueError(f"Invalid action for toggle user status: {action}")
        realm = await self._resolve_tenant_realm(tenant_id)
        res = await self._idp_admin.set_user_active(
            realm=realm,
            external_subject=idp_user_id,
            active=(action == "activate"),
        )
        if res.is_err:
            err = res.unwrap_err()
            bound_logger.error(
                "identity_sync_status_toggle_failed", code=err.code, message=err.message
            )
            raise IdentityProvisioningError(err.message)
        bound_logger.info("identity_sync_status_toggle_successful")

    async def handle_user_deleted(self, idp_user_id: str) -> None:
        bound_logger = logger.bind(idp_user_id=idp_user_id)
        bound_logger.info("syncing_user_deletion_to_identity_provider", action="delete")
        async with self.uow_factory() as uow:
            persisted_realm = await uow.repo.find_external_identity_realm(idp_user_id)
        target_realm = persisted_realm or self._default_global_realm
        res = await self._idp_admin.delete_user(
            realm=target_realm,
            external_subject=idp_user_id,
        )
        if res.is_err:
            err = res.unwrap_err()
            bound_logger.error(
                "identity_sync_user_deletion_failed",
                realm=target_realm,
                code=err.code,
                message=err.message,
            )
            raise IdentityProvisioningError(err.message)
        bound_logger.info("identity_sync_user_deletion_successful", realm=target_realm)
