from typing import Literal

import structlog

from identity_worker.adapters.outbound.identity_provider.zitadel_client import ZitadelClient
from identity_worker.adapters.outbound.identity_provider.zitadel_dtos import (
    ZitadelProjectGrantsResponse,
    ZitadelUser,
)
from identity_worker.domain.exceptions import IdentityProviderPortError
from identity_worker.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

logger = structlog.get_logger(__name__)


class ZitadelUsersAdapter(ZitadelClient, UserIdentityProviderPort):
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

            if user_res.status_code >= 400:
                await self.handle_response_error(user_res, "create user")

            data = user_res.json()
            user_data = ZitadelUser.model_validate(data)
            user_id = user_data.user_id or user_data.id
            if not user_id:
                raise ValueError("User ID not returned from Zitadel")

            logger.info("successfully_created_user_in_zitadel", user_id=user_id, org_id=org_id)
            return user_id

        except Exception as e:
            logger.exception(
                "error_creating_user_in_zitadel",
                email=self._mask_email(email),
                org_id=org_id,
            )
            raise IdentityProviderPortError("Failed to create user") from e

    async def _get_project_grant_id(self, org_id: str) -> str:
        """Internal helper to get the UCP Project Grant ID for an organization."""
        grant_search_res = await self.fetch_with_auth(
            endpoint=f"/management/v1/projects/{self.ucp_project_id}/grants/_search",
            method="POST",
            json={"queries": []},
        )
        if grant_search_res.status_code >= 400:
            await self.handle_response_error(grant_search_res, "fetch project grants")

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
            user_grant_res = await self.fetch_with_auth(
                endpoint=f"/management/v1/users/{user_id}/grants",
                method="POST",
                headers={"x-zitadel-orgid": org_id},
                json={
                    "projectId": self.ucp_project_id,
                    "projectGrantId": grant_id,
                    "roleKeys": [role],
                },
            )
            if user_grant_res.status_code >= 400:
                await self.handle_response_error(user_grant_res, "assign user role")
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
            if grants_res.status_code >= 400:
                await self.handle_response_error(grants_res, "fetch user grants")

            grants_data = grants_res.json()
            parsed_grants = ZitadelProjectGrantsResponse.model_validate(grants_data)

            user_grant = next(
                (g for g in parsed_grants.result if g.project_id == self.ucp_project_id), None
            )

            if user_grant:
                # Update existing grant
                update_res = await self.fetch_with_auth(
                    endpoint=f"/management/v1/users/{user_id}/grants/{user_grant.id}",
                    method="PUT",
                    headers={"x-zitadel-orgid": org_id},
                    json={"roleKeys": [role]},
                )
                if update_res.status_code >= 400:
                    await self.handle_response_error(update_res, "update user role")
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
            grants_res = await self.fetch_with_auth(
                endpoint="/management/v1/users/grants/_search",
                method="POST",
                headers={"x-zitadel-orgid": org_id},
                json={"queries": [{"userIdQuery": {"userId": user_id}}]},
            )
            if grants_res.status_code >= 400:
                await self.handle_response_error(grants_res, "fetch user grants")

            grants_data = grants_res.json()
            parsed_grants = ZitadelProjectGrantsResponse.model_validate(grants_data)

            user_grant = next(
                (g for g in parsed_grants.result if g.project_id == self.ucp_project_id), None
            )

            if user_grant:
                # Delete the grant
                delete_res = await self.fetch_with_auth(
                    endpoint=f"/management/v1/users/{user_id}/grants/{user_grant.id}",
                    method="DELETE",
                    headers={"x-zitadel-orgid": org_id},
                )
                if delete_res.status_code >= 400:
                    await self.handle_response_error(delete_res, "delete user grant")

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
            profile_res = await self.fetch_with_auth(
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
            if profile_res.status_code >= 400:
                err = profile_res.text
                if "Profile not changed" not in err:
                    logger.error("Failed to update user profile: {err}", err=err)
                    raise IdentityProviderPortError(
                        message=f"Failed to update user profile: {err}", original_error=err
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

        response = await self.fetch_with_auth(
            endpoint=f"/management/v1/users/{user_id}", method="DELETE"
        )

        if response.status_code >= 400:
            # Treat explicit not-found as successful idempotent deletion
            if response.status_code == 404:
                logger.info(
                    "user_not_found_in_zitadel_treating_as_deleted",
                    user_id=user_id,
                )
                return
            await self.handle_response_error(response, "delete user")

    async def toggle_user_status(
        self,
        user_id: str,
        org_id: str,
        action: Literal["activate", "deactivate"],
    ) -> None:
        logger.info("toggling_user_status_in_zitadel", user_id=user_id, action=action)

        endpoint = "_reactivate" if action == "activate" else "_deactivate"
        response = await self.fetch_with_auth(
            endpoint=f"/management/v1/users/{user_id}/{endpoint}",
            method="POST",
            headers={"x-zitadel-orgid": org_id},
        )

        if response.status_code >= 400:
            response_body = response.text
            # Handle idempotency gracefully
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
                message=f"Failed to {action} user: {response_body}", original_error=response_body
            )
