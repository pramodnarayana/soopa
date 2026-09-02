import asyncio
import contextlib
import typing
from typing import Literal

import structlog
from database.models.identity import Tenant as DbTenant
from database.models.identity import User as DbUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity_worker.ports.outbound.identity_provider_port import IdentityProviderPort
from identity_worker.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

logger = structlog.get_logger(__name__)


async def _complete_cleanup(cleanup: typing.Awaitable[None]) -> None:
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


class IdentitySyncService:
    """
    Pure business logic for synchronizing UCP domains (Tenants, Users)
    to an external Identity Provider (e.g. Zitadel).
    """

    def __init__(
        self,
        identity_provider: IdentityProviderPort,
        user_identity_provider: UserIdentityProviderPort,
        session_factory: typing.Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]]
        | None = None,
    ):
        self.identity_provider = identity_provider
        self.user_identity_provider = user_identity_provider
        self.session_factory = session_factory

    async def _resolve_idp_tenant_id(self, tenant_id: str) -> str:
        """
        Resolves the IDP tenant ID for the given platform tenant ID.
        Raises StateConflictError if the tenant is not provisioned.
        """
        if self.session_factory is None:
            raise ValueError("session_factory is required to resolve tenant IDs")

        assert self.session_factory is not None
        async with self.session_factory() as session:
            stmt = select(DbTenant).where(DbTenant.id == tenant_id)
            result = await session.execute(stmt)
            tenant = result.scalar_one_or_none()
            if not tenant or not tenant.idp_tenant_id:
                raise StateConflictError(
                    f"Tenant {tenant_id} is not fully provisioned in Identity Provider yet"
                )
            return tenant.idp_tenant_id

    async def _resolve_idp_user_id(self, user_id: str) -> str:
        """Resolve a platform user ID to its provisioned IDP user ID."""
        if self.session_factory is None:
            raise ValueError("session_factory is required to resolve user IDs")

        async with self.session_factory() as session:
            result = await session.execute(select(DbUser).where(DbUser.id == user_id))
            user = result.scalar_one_or_none()
            if not user or not user.idp_user_id:
                raise StateConflictError(
                    f"User {user_id} is not fully provisioned in Identity Provider yet"
                )
            return user.idp_user_id

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
            if self.session_factory is None:
                raise ValueError("session_factory is required to synchronize users")

            async with self.session_factory() as session:
                user_result = await session.execute(
                    select(DbUser).where(DbUser.id == user_id).with_for_update()
                )
                local_user = user_result.scalar_one_or_none()
                if not local_user:
                    bound_logger.warning("identity_sync_local_user_not_found_for_update")
                    return

                tenant_result = await session.execute(
                    select(DbTenant).where(DbTenant.id == tenant_id)
                )
                tenant = tenant_result.scalar_one_or_none()
                if not tenant or not tenant.idp_tenant_id:
                    raise StateConflictError(
                        f"Tenant {tenant_id} is not fully provisioned in Identity Provider yet"
                    )

                idp_tenant_id = tenant.idp_tenant_id
                if local_user.idp_user_id:
                    await self.user_identity_provider.assign_tenant_role(
                        user_id=local_user.idp_user_id,
                        org_id=idp_tenant_id,
                        role=role,
                    )
                    bound_logger.info(
                        "identity_sync_existing_user_reconciled",
                        idp_user_id=local_user.idp_user_id,
                    )
                    return

                created_idp_user_id: str | None = None
                try:
                    created_idp_user_id = await self.user_identity_provider.create_user(
                        org_id=idp_tenant_id,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    bound_logger.info(
                        "identity_sync_create_user_successful",
                        idp_user_id=created_idp_user_id,
                    )

                    await self.user_identity_provider.assign_tenant_role(
                        user_id=created_idp_user_id,
                        org_id=idp_tenant_id,
                        role=role,
                    )
                    bound_logger.info(
                        "identity_sync_assign_role_successful",
                        idp_user_id=created_idp_user_id,
                        role=role,
                    )

                    local_user.idp_user_id = created_idp_user_id
                    await session.commit()
                    bound_logger.info("identity_sync_updated_local_idp_user_id_successful")
                except BaseException:
                    try:
                        await _complete_cleanup(session.rollback())
                    except Exception:
                        bound_logger.exception("identity_sync_session_rollback_failed")
                    if created_idp_user_id:
                        try:
                            await _complete_cleanup(
                                self.user_identity_provider.delete_user(created_idp_user_id)
                            )
                        except Exception:
                            bound_logger.exception(
                                "identity_sync_create_user_compensation_failed",
                                idp_user_id=created_idp_user_id,
                            )
                    raise

        except Exception:
            bound_logger.exception("identity_sync_new_user_failed")
            raise

    async def handle_user_role_assigned(
        self,
        user_id: str,
        idp_user_id: str | None,
        tenant_id: str,
        role: str,
    ) -> None:
        """
        Synchronizes a role assignment to the Identity Provider.
        """
        bound_logger = logger.bind(user_id=user_id, tenant_id=tenant_id, role=role)
        bound_logger.info("syncing_user_role_assigned_to_identity_provider")

        try:
            idp_tenant_id = await self._resolve_idp_tenant_id(tenant_id)
            resolved_idp_user_id = idp_user_id or await self._resolve_idp_user_id(user_id)

            await self.user_identity_provider.assign_tenant_role(
                user_id=resolved_idp_user_id, org_id=idp_tenant_id, role=role
            )
            bound_logger.info(
                "identity_sync_assign_role_successful", idp_user_id=resolved_idp_user_id
            )
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
