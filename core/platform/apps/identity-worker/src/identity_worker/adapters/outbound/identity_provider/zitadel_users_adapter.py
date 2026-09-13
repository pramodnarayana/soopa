import asyncio
from typing import Literal

import structlog
from identity.adapters.outbound.zitadel.client import ZitadelClient
from identity.adapters.outbound.zitadel.exceptions import (
    ZitadelHttpConflictError,
    ZitadelHttpNotFoundError,
)

from identity_worker.adapters.outbound.identity_provider.zitadel_dtos import (
    ZitadelProjectGrantsResponse,
    ZitadelUser,
)
from identity_worker.config.settings import get_settings
from identity_worker.domain.exceptions import IdentityProviderPortError
from identity_worker.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

logger = structlog.get_logger(__name__)


class ZitadelUsersAdapter(ZitadelClient, UserIdentityProviderPort):
    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            api_url=settings.zitadel_api_url,
            machine_key=settings.zitadel_machine_key,
            ucp_project_id=settings.zitadel_ucp_project_id,
            default_user_password=settings.zitadel_default_user_password,
        )

    def _mask_email(self, email: str) -> str:
        parts = email.split("@")
        if len(parts) != 2:
            return email
        local, domain = parts
        if len(local) < 2:
            return f"*@{domain}"
        return f"{local[:2]}***@{domain}"

    async def create_user(
        self,
        org_id: str,
        email: str,
        first_name: str,
        last_name: str,
    ) -> str:
        logger.info(
            "creating_user_in_zitadel",
            email=self._mask_email(email),
            org_id=org_id,
        )
        try:
            user_res = await self.fetch_with_auth(
                endpoint="/management/v1/users/human",
                method="POST",
                headers={"x-zitadel-orgid": org_id},
                json={
                    "userName": email,
                    "profile": {
                        "firstName": first_name,
                        "lastName": last_name,
                        "displayName": f"{first_name} {last_name}",
                        "preferredLanguage": "en",
                    },
                    "email": {
                        "email": email,
                        "isEmailVerified": True,
                    },
                    "initialPassword": self.default_user_password,
                },
            )

            data = user_res.json()
            user_data = ZitadelUser.model_validate(data)
            user_id = user_data.user_id or user_data.id
            if not user_id:
                raise ValueError("User ID not returned from Zitadel")

            logger.info("successfully_created_user_in_zitadel", user_id=user_id, org_id=org_id)
            return user_id

        except ZitadelHttpConflictError:
            logger.info(
                "user_already_exists_in_idp_reconciling",
                email=self._mask_email(email),
                org_id=org_id,
            )
            # Zitadel is eventually consistent. The user might exist in the event log (causing 409)
            # but not yet be visible in the search projection. We must retry.
            for attempt in range(5):
                existing_user_id = await self.get_user_by_email(org_id=org_id, email=email)
                if existing_user_id:
                    return existing_user_id
                logger.info(
                    "user_not_in_projection_yet_retrying",
                    attempt=attempt,
                    email=self._mask_email(email),
                )
                # Exponential backoff: 0.5s, 1.0s, 2.0s, 4.0s, 8.0s
                await asyncio.sleep(0.5 * (2**attempt))

            raise IdentityProviderPortError(
                "User supposedly exists in IDP but could not be found by email even after retries"
            )

        except IdentityProviderPortError:
            raise
        except Exception as e:
            logger.exception(
                "error_creating_user_in_zitadel",
                email=self._mask_email(email),
                org_id=org_id,
            )
            raise IdentityProviderPortError("Failed to create user") from e

    async def get_user_by_email(self, org_id: str, email: str) -> str | None:
        try:
            res = await self.fetch_with_auth(
                endpoint="/management/v1/users/_search",
                method="POST",
                headers={"x-zitadel-orgid": org_id},
                json={
                    "query": {"limit": 1},
                    "queries": [
                        {
                            "userNameQuery": {
                                "userName": email,
                                "method": "TEXT_QUERY_METHOD_EQUALS_IGNORE_CASE",
                            }
                        }
                    ],
                },
            )
            data = res.json()
            results = data.get("result", [])
            if not results:
                return None

            user_id = results[0].get("id")
            if not user_id:
                return None

            return user_id

        except IdentityProviderPortError:
            raise
        except Exception as e:
            logger.exception(
                "error_fetching_user_by_email",
                email=self._mask_email(email),
                org_id=org_id,
            )
            raise IdentityProviderPortError("Failed to fetch user by email") from e

    async def _get_project_grant_id(self, org_id: str) -> str:
        """Internal helper to get the UCP Project Grant ID for an organization."""
        grant_search_res = await self.fetch_with_auth(
            endpoint=f"/management/v1/projects/{self.ucp_project_id}/grants/_search",
            method="POST",
            json={"queries": []},
        )
        grant_search_data = grant_search_res.json()
        parsed_grant_data = ZitadelProjectGrantsResponse.model_validate(grant_search_data)

        project_grant = next(
            (g for g in parsed_grant_data.result if g.granted_org_id == org_id), None
        )
        if not project_grant:
            raise IdentityProviderPortError(f"No UCP project grant found for org {org_id}")

        grant_id = project_grant.grant_id or project_grant.id
        if not grant_id:
            raise IdentityProviderPortError("Grant ID missing in Zitadel response")

        return grant_id

    async def assign_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        logger.info(
            "assigning_role_to_user_in_zitadel",
            role=role,
            user_id=user_id,
            org_id=org_id,
        )
        try:
            grant_id = await self._get_project_grant_id(org_id)
            await self.fetch_with_auth(
                endpoint=f"/management/v1/users/{user_id}/grants",
                method="POST",
                headers={"x-zitadel-orgid": org_id},
                json={
                    "projectId": self.ucp_project_id,
                    "projectGrantId": grant_id,
                    "roleKeys": [role],
                },
            )
        except Exception as e:
            logger.exception(
                "error_assigning_role_for_user",
                user_id=user_id,
                org_id=org_id,
            )
            raise IdentityProviderPortError("Failed to assign role") from e

    async def update_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        logger.info(
            "updating_role_for_user_in_zitadel",
            role=role,
            user_id=user_id,
            org_id=org_id,
        )
        try:
            grants_res = await self.fetch_with_auth(
                endpoint="/management/v1/users/grants/_search",
                method="POST",
                headers={"x-zitadel-orgid": org_id},
                json={"queries": [{"userIdQuery": {"userId": user_id}}]},
            )
            grants_data = grants_res.json()
            parsed_grants = ZitadelProjectGrantsResponse.model_validate(grants_data)

            user_grant = next(
                (g for g in parsed_grants.result if g.project_id == self.ucp_project_id), None
            )

            if user_grant:
                # Update existing grant
                await self.fetch_with_auth(
                    endpoint=f"/management/v1/users/{user_id}/grants/{user_grant.id}",
                    method="PUT",
                    headers={"x-zitadel-orgid": org_id},
                    json={"roleKeys": [role]},
                )
            else:
                # User had no grant, assign fresh
                await self.assign_tenant_role(user_id, org_id, role)

        except Exception as e:
            logger.exception(
                "error_updating_role_for_user",
                user_id=user_id,
                org_id=org_id,
            )
            raise IdentityProviderPortError("Failed to update role") from e

    async def remove_tenant_role(self, user_id: str, org_id: str) -> None:
        logger.info(
            "removing_role_for_user_in_zitadel",
            user_id=user_id,
            org_id=org_id,
        )
        try:
            limit = 100
            offset = 0
            all_grants = []

            while True:
                grants_res = await self.fetch_with_auth(
                    endpoint="/management/v1/users/grants/_search",
                    method="POST",
                    headers={"x-zitadel-orgid": org_id},
                    json={
                        "query": {"limit": limit, "offset": offset},
                        "queries": [{"userIdQuery": {"userId": user_id}}],
                    },
                )
                grants_data = grants_res.json()
                parsed_grants = ZitadelProjectGrantsResponse.model_validate(grants_data)

                if parsed_grants.result:
                    all_grants.extend(parsed_grants.result)

                total_result = (
                    parsed_grants.details.total_result
                    if parsed_grants.details and parsed_grants.details.total_result is not None
                    else 0
                )
                offset += len(parsed_grants.result) if parsed_grants.result else 0

                if offset >= total_result or not parsed_grants.result:
                    break

            user_grant = next((g for g in all_grants if g.project_id == self.ucp_project_id), None)

            if user_grant:
                # Delete the grant
                await self.fetch_with_auth(
                    endpoint=f"/management/v1/users/{user_id}/grants/{user_grant.id}",
                    method="DELETE",
                    headers={"x-zitadel-orgid": org_id},
                )

        except Exception as e:
            logger.exception(
                "error_removing_role_for_user",
                user_id=user_id,
                org_id=org_id,
            )
            raise IdentityProviderPortError("Failed to remove role") from e

    async def update_user_profile(
        self,
        user_id: str,
        org_id: str,
        first_name: str,
        last_name: str,
    ) -> None:
        logger.info("updating_profile_for_user_in_zitadel", user_id=user_id, org_id=org_id)
        try:
            await self.fetch_with_auth(
                endpoint=f"/management/v1/users/{user_id}/profile",
                method="PUT",
                headers={"x-zitadel-orgid": org_id},
                json={
                    "firstName": first_name,
                    "lastName": last_name,
                    "displayName": f"{first_name} {last_name}",
                    "preferredLanguage": "en",
                },
            )
        except Exception as e:
            logger.exception(
                "error_updating_profile_for_user",
                user_id=user_id,
                org_id=org_id,
            )
            raise IdentityProviderPortError("Failed to update profile") from e

    async def delete_user(self, user_id: str) -> None:
        logger.info("deleting_user_from_zitadel", user_id=user_id)

        try:
            await self.fetch_with_auth(endpoint=f"/management/v1/users/{user_id}", method="DELETE")

        except ZitadelHttpNotFoundError:
            logger.info(
                "user_not_found_in_zitadel_treating_as_deleted",
                user_id=user_id,
            )
            return

    async def toggle_user_status(
        self,
        user_id: str,
        org_id: str,
        action: Literal["activate", "deactivate"],
    ) -> None:
        logger.info("toggling_user_status_in_zitadel", user_id=user_id, action=action)

        endpoint = "_reactivate" if action == "activate" else "_deactivate"
        try:
            await self.fetch_with_auth(
                endpoint=f"/management/v1/users/{user_id}/{endpoint}",
                method="POST",
                headers={"x-zitadel-orgid": org_id},
            )

        except Exception as e:  # noqa: BLE001
            # Handle idempotency gracefully
            if hasattr(e, "original_error") and e.original_error:
                response_body = str(e.original_error)
                if (action == "deactivate" and "User already inactive" in response_body) or (
                    action == "activate" and "User already active" in response_body
                ):
                    logger.info(
                        "user_already_in_target_status_ignoring_error",
                        user_id=user_id,
                        action=action,
                    )
                    return

            raise IdentityProviderPortError(
                message=f"Failed to {action} user: {e}",
                original_error=e,
            )
