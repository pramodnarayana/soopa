from typing import Any

import structlog

from identity_worker.adapters.outbound.identity_provider.zitadel_client import ZitadelClient
from identity_worker.adapters.outbound.identity_provider.zitadel_dtos import (
    ZitadelProjectGrantsResponse,
    ZitadelRawUserSearchResponse,
    ZitadelRolesResponse,
)
from identity_worker.application.dto import IdpRole, IdpUser
from identity_worker.domain.exceptions import IdentityProviderPortError
from identity_worker.ports.outbound.project_provider_port import ProjectProviderPort

logger = structlog.get_logger(__name__)


class ZitadelProjectsAdapter(ZitadelClient, ProjectProviderPort):
    _MAX_SEARCH_PAGES = 1_000

    async def _search_all(
        self,
        endpoint: str,
        *,
        headers: dict[str, str] | None = None,
        queries: list[dict[str, Any]] | None = None,
    ) -> list[Any]:
        offset = 0
        limit = 100
        page_count = 0
        results: list[Any] = []

        while True:
            if page_count >= self._MAX_SEARCH_PAGES:
                raise IdentityProviderPortError(
                    f"ZITADEL search exceeded {self._MAX_SEARCH_PAGES} pages"
                )
            page_count += 1

            response = await self.fetch_with_auth(
                endpoint=endpoint,
                method="POST",
                headers=headers,
                json={
                    "query": {"offset": offset, "limit": limit},
                    "queries": queries or [],
                },
            )
            if response.status_code >= 400:
                await self.handle_response_error(response, f"search {endpoint}")

            data = response.json()
            page = data.get("result", [])
            if not isinstance(page, list):
                raise IdentityProviderPortError("Invalid paginated response from ZITADEL")
            results.extend(page)
            offset += len(page)

            details = data.get("details", {})
            raw_total = details.get("totalResult") if isinstance(details, dict) else None
            total = (
                int(raw_total)
                if isinstance(raw_total, int)
                or (isinstance(raw_total, str) and raw_total.isdigit())
                else None
            )
            if not page or (total is not None and offset >= total):
                return results
            if total is None and len(page) < limit:
                return results

    async def create_project_grant(
        self, org_id: str, project_id: str, role_keys: list[str]
    ) -> None:
        logger.info(
            "creating_project_grant_in_zitadel",
            org_id=org_id,
            project_id=project_id,
        )

        try:
            response = await self.fetch_with_auth(
                endpoint=f"/management/v1/projects/{project_id}/grants",
                method="POST",
                json={
                    "grantedOrgId": org_id,
                    "roleKeys": role_keys,
                },
            )

            if response.status_code >= 400:
                await self.handle_response_error(response, "create project grant")

            logger.info(
                "successfully_granted_project_to_organization",
                project_id=project_id,
                org_id=org_id,
            )
        except Exception as e:
            logger.exception("error_creating_project_grant", org_id=org_id)
            raise IdentityProviderPortError("Failed to create project grant") from e

    async def delete_project_grant(self, org_id: str, project_id: str) -> None:
        logger.info(
            "deleting_project_grant_in_zitadel",
            org_id=org_id,
            project_id=project_id,
        )

        try:
            # First, search for the grant to get its ID
            search_data = await self._search_all(
                endpoint=f"/management/v1/projects/{project_id}/grants/_search"
            )
            parsed_search_data = ZitadelProjectGrantsResponse.model_validate(
                {"result": search_data}
            )

            grant = next((g for g in parsed_search_data.result if g.granted_org_id == org_id), None)

            if not grant:
                logger.warning(
                    "project_grant_not_found_skipping_deletion",
                    org_id=org_id,
                    project_id=project_id,
                )
                return

            grant_id = grant.grant_id or grant.id

            # Delete the grant
            delete_response = await self.fetch_with_auth(
                endpoint=f"/management/v1/projects/{project_id}/grants/{grant_id}", method="DELETE"
            )

            if delete_response.status_code >= 400:
                await self.handle_response_error(delete_response, "delete project grant")

            logger.info(
                "successfully_revoked_project_from_organization",
                project_id=project_id,
                org_id=org_id,
            )
        except Exception as e:
            logger.exception("error_deleting_project_grant", org_id=org_id)
            raise IdentityProviderPortError("Failed to delete project grant") from e

    async def get_roles(self) -> list[IdpRole]:
        logger.info("fetching_roles_for_ucp_project")

        data = await self._search_all(
            endpoint=f"/management/v1/projects/{self.ucp_project_id}/roles/_search"
        )
        parsed_data = ZitadelRolesResponse.model_validate({"result": data})
        return [
            IdpRole(
                key=role.key or "",
                display_name=role.display_name or "",
                group=role.group or ""
            )
            for role in parsed_data.result
        ]

    async def get_users(self, org_id: str) -> list[IdpUser]:
        logger.info("fetching_users_for_org", org_id=org_id)

        # 1. Fetch all users in the org
        data = await self._search_all(
            endpoint="/management/v1/users/_search",
            headers={"x-zitadel-orgid": org_id},
        )
        raw_users_data = ZitadelRawUserSearchResponse.model_validate({"result": data})
        users = raw_users_data.result

        users_with_roles = []
        for u in users:
            email = u.human.email.email if u.human and u.human.email else u.user_name
            # display_name was originally extracted here but left unused
            first_name = u.human.profile.first_name if u.human and u.human.profile else ""
            last_name = u.human.profile.last_name if u.human and u.human.profile else ""

            users_with_roles.append(
                IdpUser(
                    id=u.id or "",
                    email=email or "",
                    preferred_login_name=u.user_name or "",
                    first_name=first_name or "",
                    last_name=last_name or "",
                    state=u.state or "",
                )
            )

        return users_with_roles
