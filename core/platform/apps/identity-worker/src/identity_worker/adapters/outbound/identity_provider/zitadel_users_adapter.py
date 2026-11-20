from enum import IntEnum
from typing import Literal

import httpx
import structlog
from seedwork.domain.types import JsonValue
from shttp import HttpClient

from identity_worker.adapters.outbound.identity_provider.zitadel_dtos import (
    ZitadelProjectGrantsResponse,
)
from identity_worker.config.settings import AppSettings
from identity_worker.domain.exceptions import IdentityProviderPortError
from identity_worker.ports.outbound.user_identity_provider_port import UserIdentityProviderPort

logger = structlog.get_logger(__name__)


class _GrpcStatusCode(IntEnum):
    FAILED_PRECONDITION = 9


_ZITADEL_STATE_PRECONDITIONS: dict[Literal["activate", "deactivate"], str] = {
    "activate": "already active",
    "deactivate": "already inactive",
}


def _is_already_in_target_status(
    response: httpx.Response,
    action: Literal["activate", "deactivate"],
) -> bool:
    """Inspect structured Zitadel gRPC-Gateway error envelope for idempotent state transitions."""
    try:
        payload: object = response.json()
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    code = payload.get("code")
    message = payload.get("message")
    if code != _GrpcStatusCode.FAILED_PRECONDITION or not isinstance(message, str):
        return False
    return _ZITADEL_STATE_PRECONDITIONS[action] in message.lower()


class ZitadelUsersAdapter(UserIdentityProviderPort):
    def __init__(
        self,
        http_client: HttpClient,
        settings: AppSettings,
    ) -> None:
        self._http_client = http_client
        self.settings = settings
        self.default_user_password = self.settings.idp_default_user_password

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
        res = await self._http_client.post(
            "/v2/users/human",
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
            data = res.json()
            actual_id = str(data.get("userId") or data.get("id") or user_id)
            logger.info("successfully_created_user_in_zitadel", user_id=actual_id, org_id=org_id)
            return actual_id, True

        is_already_existing = res.status_code == 409 or (
            res.status_code == 400 and "Errors.User.AlreadyExisting" in res.text
        )
        if is_already_existing:
            logger.info(
                "user_conflict_attempting_deterministic_recovery",
                email=self._mask_email(email),
                org_id=org_id,
                user_id=user_id,
            )
            # Deterministic idempotency: Verify if user exists in target organization
            recovered_id = await self.get_user_by_email(org_id, email)
            if not recovered_id and org_id != self.settings.platform_org_id:
                recovered_id = await self.get_user_by_email(self.settings.platform_org_id, email)

            if recovered_id:
                logger.info(
                    "recovered_existing_user_from_zitadel",
                    user_id=recovered_id,
                    email=self._mask_email(email),
                )
                return recovered_id, False

            # Check if user exists with our specific UUID
            get_res = await self._http_client.get(
                f"/management/v1/users/{user_id}",
                headers={"x-zitadel-orgid": org_id},
            )
            if get_res.status_code == 200:
                logger.info("recovered_existing_user_by_id_from_zitadel", user_id=user_id)
                return user_id, False

            logger.error(
                "genuine_duplicate_user_email",
                email=self._mask_email(email),
                status_code=res.status_code,
                body=res.text,
            )
            raise IdentityProviderPortError(f"Email '{self._mask_email(email)}' is already taken.")

        logger.error(
            "error_creating_user_in_zitadel",
            email=self._mask_email(email),
            org_id=org_id,
            status_code=res.status_code,
            body=res.text,
        )
        raise IdentityProviderPortError(f"Failed to create user: {res.text}")

    async def get_user_by_email(self, org_id: str, email: str) -> str | None:
        res = await self._http_client.post(
            "/management/v1/users/_search",
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
            # Fallback search by emailAddress in case username differs
            email_res = await self._http_client.post(
                "/management/v1/users/_search",
                headers={"x-zitadel-orgid": org_id},
                json={
                    "query": {"limit": 1},
                    "queries": [
                        {
                            "emailQuery": {
                                "emailAddress": email,
                                "method": "TEXT_QUERY_METHOD_EQUALS_IGNORE_CASE",
                            }
                        }
                    ],
                },
            )
            if not email_res.is_error:
                results = email_res.json().get("result", [])

        if not results:
            return None

        user_id = results[0].get("id")
        return user_id or None

    async def _get_project_and_grant_id(
        self, org_id: str, project_id: str | None = None
    ) -> tuple[str, str]:
        """Resolves the (project_id, grant_id) for an organization."""
        target_project_id = project_id or self.settings.control_plane_project_id
        if target_project_id:
            grant_search_res = await self._http_client.post(
                f"/management/v1/projects/{target_project_id}/grants/_search",
                headers={"x-zitadel-orgid": self.settings.platform_org_id},
                json={"queries": []},
            )
            if grant_search_res.is_error:
                logger.error(
                    "failed_to_search_project_grants",
                    project_id=target_project_id,
                    status_code=grant_search_res.status_code,
                    body=grant_search_res.text,
                )
                raise IdentityProviderPortError(
                    f"Failed to lookup project grants for project {target_project_id}"
                )

            grant_search_data = grant_search_res.json()
            parsed_grant_data = ZitadelProjectGrantsResponse.model_validate(grant_search_data)
            project_grant = next(
                (g for g in parsed_grant_data.result if g.granted_org_id == org_id), None
            )
            if project_grant:
                grant_id = project_grant.grant_id or project_grant.id
                if not grant_id:
                    raise IdentityProviderPortError("Grant ID missing in Zitadel response")
                return target_project_id, grant_id

        # If project_id is not passed, resolve granted projects for this org
        grant_search_res = await self._http_client.post(
            "/management/v1/projectgrants/_search",
            headers={"x-zitadel-orgid": org_id},
            json={"queries": []},
        )
        if grant_search_res.is_error:
            logger.error(
                "failed_to_search_org_project_grants",
                org_id=org_id,
                status_code=grant_search_res.status_code,
                body=grant_search_res.text,
            )
            raise IdentityProviderPortError(f"Failed to lookup project grants for org {org_id}")

        grant_search_data = grant_search_res.json()
        parsed_grant_data = ZitadelProjectGrantsResponse.model_validate(grant_search_data)
        if not parsed_grant_data.result:
            raise IdentityProviderPortError(f"No project grants found for org {org_id}")

        target_grant = parsed_grant_data.result[0]
        resolved_project_id = target_grant.project_id
        resolved_grant_id = target_grant.grant_id or target_grant.id
        if not resolved_project_id or not resolved_grant_id:
            raise IdentityProviderPortError(f"Invalid project grant metadata for org {org_id}")
        return resolved_project_id, resolved_grant_id

    async def assign_tenant_role(
        self, user_id: str, org_id: str, role: str, project_id: str | None = None
    ) -> None:
        logger.info(
            "assigning_role_to_user_in_zitadel",
            role=role,
            user_id=user_id,
            org_id=org_id,
            project_id=project_id,
        )
        resolved_project_id, grant_id = await self._get_project_and_grant_id(org_id, project_id)
        role_keys: list[JsonValue] = [role]
        res = await self._http_client.post(
            f"/management/v1/users/{user_id}/grants",
            headers={"x-zitadel-orgid": org_id},
            json={
                "projectId": resolved_project_id,
                "projectGrantId": grant_id,
                "roleKeys": role_keys,
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
        raise IdentityProviderPortError("Failed to assign role to user in identity provider")

    async def update_tenant_role(
        self, user_id: str, org_id: str, role: str, project_id: str | None = None
    ) -> None:
        logger.info(
            "updating_role_for_user_in_zitadel",
            role=role,
            user_id=user_id,
            org_id=org_id,
            project_id=project_id,
        )
        grants_res = await self._http_client.post(
            "/management/v1/users/grants/_search",
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

        user_grant = (
            next((g for g in parsed_grants.result if g.project_id == project_id), None)
            if project_id
            else (parsed_grants.result[0] if parsed_grants.result else None)
        )

        if user_grant:
            grant_id = user_grant.grant_id or user_grant.id
            role_keys: list[JsonValue] = [role]
            update_res = await self._http_client.put(
                f"/management/v1/users/{user_id}/grants/{grant_id}",
                headers={"x-zitadel-orgid": org_id},
                json={"roleKeys": role_keys},
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
            await self.assign_tenant_role(user_id, org_id, role, project_id)

    async def remove_tenant_role(
        self, user_id: str, org_id: str, project_id: str | None = None
    ) -> None:
        logger.info(
            "removing_role_for_user_in_zitadel",
            user_id=user_id,
            org_id=org_id,
            project_id=project_id,
        )
        limit = 100
        offset = 0
        all_grants = []

        while True:
            grants_res = await self._http_client.post(
                "/management/v1/users/grants/_search",
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

        target_grants = (
            [g for g in all_grants if g.project_id == project_id] if project_id else all_grants
        )

        for user_grant in target_grants:
            grant_id = user_grant.grant_id or user_grant.id
            if not grant_id:
                continue
            del_res = await self._http_client.delete(
                f"/management/v1/users/{user_id}/grants/{grant_id}",
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
        res = await self._http_client.put(
            f"/management/v1/users/{user_id}/profile",
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
        res = await self._http_client.delete(f"/management/v1/users/{user_id}")
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
        res = await self._http_client.post(
            f"/management/v1/users/{user_id}/{endpoint}",
            headers={"x-zitadel-orgid": org_id},
        )
        if res.status_code in (200, 204):
            return

        if _is_already_in_target_status(res, action):
            logger.info(
                "user_already_in_target_status_ignoring_error",
                user_id=user_id,
                action=action,
            )
            return

        body = res.text
        logger.error(
            "error_toggling_user_status",
            user_id=user_id,
            status_code=res.status_code,
            body=body,
        )
        raise IdentityProviderPortError(f"Failed to {action} user: {body}")
