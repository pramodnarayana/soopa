import structlog

from ucp.adapters.outbound.identity.zitadel_client import ZitadelClient
from ucp.domain.dtos.zitadel_dtos import (
    ZitadelProjectGrantsResponse,
    ZitadelRawUserSearchResponse,
    ZitadelRole,
    ZitadelRolesResponse,
    ZitadelUser,
)
from ucp.ports.outbound.project_provider_port import ProjectProviderPort

logger = structlog.get_logger(__name__)


class ZitadelProjectsAdapter(ZitadelClient, ProjectProviderPort):
    async def create_project_grant(
        self, org_id: str, project_id: str, role_keys: list[str]
    ) -> None:
        logger.info(
            "Creating project grant in Zitadel. OrgId: {org_id}, ProjectId: {project_id}",
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
                "Successfully granted Project {project_id} to Organization {org_id}",
                project_id=project_id,
                org_id=org_id,
            )
        except Exception:
            logger.exception("Error creating project grant for org {org_id}", org_id=org_id)

            raise

    async def delete_project_grant(self, org_id: str, project_id: str) -> None:
        logger.info(
            "Deleting project grant in Zitadel. OrgId: {org_id}, ProjectId: {project_id}",
            org_id=org_id,
            project_id=project_id,
        )

        try:
            # First, search for the grant to get its ID
            search_response = await self.fetch_with_auth(
                endpoint=f"/management/v1/projects/{project_id}/grants/_search",
                method="POST",
                json={"queries": []},
            )

            if search_response.status_code >= 400:
                await self.handle_response_error(search_response, "search project grants")

            search_data = search_response.json()
            parsed_search_data = ZitadelProjectGrantsResponse.model_validate(search_data)

            grant = next((g for g in parsed_search_data.result if g.granted_org_id == org_id), None)

            if not grant:
                logger.warning(
                    "No project grant found for org {org_id} and project {project_id}. Skipping deletion.",
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
                "Successfully revoked Project {project_id} from Organization {org_id}",
                project_id=project_id,
                org_id=org_id,
            )
        except Exception:
            logger.exception("Error deleting project grant for org {org_id}", org_id=org_id)

            raise

    async def get_roles(self) -> list[ZitadelRole]:
        logger.info("Fetching roles for UCP Project")

        response = await self.fetch_with_auth(
            endpoint=f"/management/v1/projects/{self.ucp_project_id}/roles/_search",
            method="POST",
            json={},
        )

        if response.status_code >= 400:
            await self.handle_response_error(response, "fetch roles")

        data = response.json()
        parsed_data = ZitadelRolesResponse.model_validate(data)
        return parsed_data.result

    async def get_users(self, org_id: str) -> list[ZitadelUser]:
        logger.info("Fetching users for org {org_id}", org_id=org_id)

        # 1. Fetch all users in the org
        response = await self.fetch_with_auth(
            endpoint="/management/v1/users/_search",
            method="POST",
            headers={"x-zitadel-orgid": org_id},
            json={},
        )

        if response.status_code >= 400:
            await self.handle_response_error(response, "fetch users")

        data = response.json()
        raw_users_data = ZitadelRawUserSearchResponse.model_validate(data)
        users = raw_users_data.result

        # 2. Fetch all grants for the UCP Project in this Org
        grants = []
        try:
            grant_res = await self.fetch_with_auth(
                endpoint=f"/management/v1/projects/{self.ucp_project_id}/grants/_search",
                method="POST",
                json={"queries": []},
            )
            if grant_res.status_code < 400:
                grant_data = grant_res.json()
                parsed_grant_data = ZitadelProjectGrantsResponse.model_validate(grant_data)
                grants = parsed_grant_data.result
        except Exception:  # noqa: BLE001 - grant fetch is non-critical; empty grants is a safe fallback
            logger.warning("Failed to fetch grants for org %s", org_id)

        # 3. Map grants to users in memory
        org_grant = next((g for g in grants if g.granted_org_id == org_id), None)
        role = org_grant.role_keys[0] if org_grant and org_grant.role_keys else "Unknown"

        users_with_roles = []
        for u in users:
            email = u.human.email.email if u.human and u.human.email else u.user_name
            display_name = (
                u.human.profile.display_name if u.human and u.human.profile else u.user_name
            )
            first_name = u.human.profile.first_name if u.human and u.human.profile else None
            last_name = u.human.profile.last_name if u.human and u.human.profile else None

            users_with_roles.append(
                ZitadelUser(
                    userId=u.id,
                    email=email,
                    displayName=display_name,
                    firstName=first_name,
                    lastName=last_name,
                    state=u.state,
                    role=role,
                    createdAt=u.details.creation_date if u.details else None,
                )
            )

        return users_with_roles
