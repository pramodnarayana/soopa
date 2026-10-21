from typing import Literal

import structlog
from identity.adapters.outbound.zitadel.client import ZitadelClient

from identity_worker.adapters.outbound.identity_provider.zitadel_dtos import (
    ZitadelProjectGrantsResponse,
)
from identity_worker.config.settings import AppSettings, get_settings
from identity_worker.domain.exceptions import IdentityProviderPortError
from identity_worker.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

logger = structlog.get_logger(__name__)


class ZitadelUsersAdapter(ZitadelClient, UserIdentityProviderPort):
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        super().__init__(
            api_url=self.settings.zitadel_api_url,
            machine_key=self.settings.zitadel_machine_key,
            ucp_project_id=self.settings.zitadel_ucp_project_id,
            default_user_password=self.settings.zitadel_default_user_password,
            platform_org_id=self.settings.zitadel_platform_org_id,
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
        user_id: str,
        email: str,
        first_name: str,
        last_name: str,
    ) -> tuple[str, bool]:
        logger.info(
            "creating_user_in_zitadel",
            email=self._mask_email(email),
            org_id=org_id,
            user_id=user_id,
        )
        res = await self.fetch_with_auth(
            endpoint="/v2/users/human",
            method="POST",
            headers={"x-zitadel-orgid": org_id},
            json={
                "userId": user_id,
                "username": email,
                "profile": {
                    "givenName": first_name,
                    "familyName": last_name,
                },
                "email": {
                    "email": email,
                    "isVerified": True,
                },
                "password": {
                    "password": self.default_user_password,
                    "changeRequired": False,
                },
            },
        )

        if res.status_code in (200, 201):
            logger.info("successfully_created_user_in_zitadel", user_id=user_id, org_id=org_id)
            return user_id, True

        if res.status_code == 409:
            logger.info(
                "user_conflict_attempting_deterministic_recovery",
                email=self._mask_email(email),
                org_id=org_id,
                user_id=user_id,
            )
            # Deterministic idempotency: Verify if user exists with OUR specific UUID
            get_res = await self.fetch_with_auth(
                endpoint=f"/management/v1/users/{user_id}",
                method="GET",
                headers={"x-zitadel-orgid": org_id},
            )
            if get_res.status_code == 200:
                logger.info("recovered_existing_user_from_zitadel", user_id=user_id)
                return user_id, False
            if get_res.status_code == 404:
                logger.error(
                    "genuine_duplicate_user_email",
                    email=self._mask_email(email),
                )
                raise IdentityProviderPortError(
                    f"Email '{self._mask_email(email)}' is already taken."
                )

            logger.error(
                "failed_to_recover_existing_user",
                email=self._mask_email(email),
                user_id=user_id,
                status_code=get_res.status_code,
                body=get_res.text,
            )
            raise IdentityProviderPortError("Failed to recover existing user")

        logger.error(
            "error_creating_user_in_zitadel",
            email=self._mask_email(email),
            org_id=org_id,
            status_code=res.status_code,
            body=res.text,
        )
        raise IdentityProviderPortError(f"Failed to create user: {res.text}")

    async def get_user_by_email(self, org_id: str, email: str) -> str | None:
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
        if res.is_error:
            logger.error(
                "error_fetching_user_by_email",
                email=self._mask_email(email),
                org_id=org_id,
                status_code=res.status_code,
                body=res.text,
            )
            raise IdentityProviderPortError("Failed to fetch user by email")

        data = res.json()
        results = data.get("result", [])
        if not results:
            return None

        user_id = results[0].get("id")
        return user_id or None

    async def _get_project_grant_id(self, org_id: str) -> str:
        """Internal helper to get the UCP Project Grant ID for an organization."""
        grant_search_res = await self.fetch_with_auth(
            endpoint=f"/management/v1/projects/{self.ucp_project_id}/grants/_search",
            method="POST",
            headers={"x-zitadel-orgid": self.settings.zitadel_platform_org_id},
            json={"queries": []},
        )
        if grant_search_res.is_error:
            logger.error(
                "failed_to_search_project_grants",
                status_code=grant_search_res.status_code,
                body=grant_search_res.text,
            )
            raise IdentityProviderPortError(f"Failed to lookup project grants for org {org_id}")

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
        grant_id = await self._get_project_grant_id(org_id)
        res = await self.fetch_with_auth(
            endpoint=f"/management/v1/users/{user_id}/grants",
            method="POST",
            headers={"x-zitadel-orgid": org_id},
            json={
                "projectId": self.ucp_project_id,
                "projectGrantId": grant_id,
                "roleKeys": [role],
            },
        )
        if res.status_code in (200, 201):
            return
        if res.status_code == 409:
            logger.info("user_role_already_assigned", user_id=user_id, role=role)
            return

        logger.error(
            "error_assigning_role_for_user",
            user_id=user_id,
            org_id=org_id,
            status_code=res.status_code,
            body=res.text,
        )
        raise IdentityProviderPortError(f"Failed to assign role: {res.text}")

    async def update_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        logger.info(
            "updating_role_for_user_in_zitadel",
            role=role,
            user_id=user_id,
            org_id=org_id,
        )
        grants_res = await self.fetch_with_auth(
            endpoint="/management/v1/users/grants/_search",
            method="POST",
            headers={"x-zitadel-orgid": org_id},
            json={"queries": [{"userIdQuery": {"userId": user_id}}]},
        )
        if grants_res.is_error:
            logger.error(
                "error_searching_user_grants",
                user_id=user_id,
                status_code=grants_res.status_code,
                body=grants_res.text,
            )
            raise IdentityProviderPortError("Failed to search user grants")

        grants_data = grants_res.json()
        parsed_grants = ZitadelProjectGrantsResponse.model_validate(grants_data)

        user_grant = next(
            (g for g in parsed_grants.result if g.project_id == self.ucp_project_id), None
        )

        if user_grant:
            update_res = await self.fetch_with_auth(
                endpoint=f"/management/v1/users/{user_id}/grants/{user_grant.id}",
                method="PUT",
                headers={"x-zitadel-orgid": org_id},
                json={"roleKeys": [role]},
            )
            if not update_res.is_success:
                logger.error(
                    "error_updating_role_for_user",
                    user_id=user_id,
                    status_code=update_res.status_code,
                    body=update_res.text,
                )
                raise IdentityProviderPortError("Failed to update role")
        else:
            await self.assign_tenant_role(user_id, org_id, role)

    async def remove_tenant_role(self, user_id: str, org_id: str) -> None:
        logger.info(
            "removing_role_for_user_in_zitadel",
            user_id=user_id,
            org_id=org_id,
        )
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
            if grants_res.is_error:
                logger.error(
                    "error_searching_user_grants_for_removal",
                    user_id=user_id,
                    status_code=grants_res.status_code,
                    body=grants_res.text,
                )
                raise IdentityProviderPortError("Failed to search user grants for removal")

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
            del_res = await self.fetch_with_auth(
                endpoint=f"/management/v1/users/{user_id}/grants/{user_grant.id}",
                method="DELETE",
                headers={"x-zitadel-orgid": org_id},
            )
            if del_res.status_code not in (200, 204, 404):
                logger.error(
                    "error_deleting_user_grant",
                    user_id=user_id,
                    status_code=del_res.status_code,
                    body=del_res.text,
                )
                raise IdentityProviderPortError("Failed to delete user grant")

    async def update_user_profile(
        self,
        user_id: str,
        org_id: str,
        first_name: str,
        last_name: str,
    ) -> None:
        logger.info("updating_profile_for_user_in_zitadel", user_id=user_id, org_id=org_id)
        res = await self.fetch_with_auth(
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
        if res.status_code in (200, 204):
            return

        logger.error(
            "error_updating_profile_for_user",
            user_id=user_id,
            org_id=org_id,
            status_code=res.status_code,
            body=res.text,
        )
        raise IdentityProviderPortError("Failed to update profile")

    async def delete_user(self, user_id: str) -> None:
        logger.info("deleting_user_from_zitadel", user_id=user_id)
        res = await self.fetch_with_auth(
            endpoint=f"/management/v1/users/{user_id}", method="DELETE"
        )
        if res.status_code in (200, 204):
            return
        if res.status_code == 404:
            logger.info("user_not_found_in_zitadel_treating_as_deleted", user_id=user_id)
            return

        logger.error(
            "error_deleting_user_from_zitadel",
            user_id=user_id,
            status_code=res.status_code,
            body=res.text,
        )
        raise IdentityProviderPortError("Failed to delete user")

    async def toggle_user_status(
        self,
        user_id: str,
        org_id: str,
        action: Literal["activate", "deactivate"],
    ) -> None:
        logger.info("toggling_user_status_in_zitadel", user_id=user_id, action=action)

        endpoint = "_reactivate" if action == "activate" else "_deactivate"
        res = await self.fetch_with_auth(
            endpoint=f"/management/v1/users/{user_id}/{endpoint}",
            method="POST",
            headers={"x-zitadel-orgid": org_id},
        )
        if res.status_code in (200, 204):
            return

        body = res.text
        if (action == "deactivate" and "User already inactive" in body) or (
            action == "activate" and "User already active" in body
        ):
            logger.info(
                "user_already_in_target_status_ignoring_error",
                user_id=user_id,
                action=action,
            )
            return

        logger.error(
            "error_toggling_user_status",
            user_id=user_id,
            status_code=res.status_code,
            body=body,
        )
        raise IdentityProviderPortError(f"Failed to {action} user: {body}")
