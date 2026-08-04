import logging
from typing import Tuple
from ucp_api.adapters.outbound.identity.zitadel_client import ZitadelClient
from ucp_api.ports.outbound.organization_provider import IOrganizationProvider
from ucp_api.ports.outbound.project_provider import IProjectProvider
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CreateOrgResponse(BaseModel):
    id: str | None = None
    organization_id: str | None = Field(None, alias="organizationId")
    org_id: str | None = Field(None, alias="orgId")


class ZitadelOrganizationsAdapter(ZitadelClient, IOrganizationProvider):
    def __init__(self, project_provider: IProjectProvider) -> None:
        super().__init__()
        self.project_provider = project_provider

    async def create_organization(self, name: str) -> Tuple[str, bool]:
        logger.info(f"Provisioning Organization in Zitadel: {name}")

        try:
            response = await self.fetch_with_auth(
                endpoint="/management/v1/orgs", method="POST", json={"name": name}
            )

            if response.status_code >= 400:
                await self.handle_response_error(response, "create org")

            data = response.json()
            parsed_data = CreateOrgResponse.model_validate(data)
            org_id = parsed_data.id or parsed_data.organization_id or parsed_data.org_id

            if not org_id:
                raise ValueError("Org ID not returned from Zitadel")

            logger.info(f"Created Organization in Zitadel with ID: {org_id}")

            grant_succeeded = False
            if self.ucp_project_id:
                tenant_group = self.settings.zitadel_tenant_role_group
                all_roles = await self.project_provider.get_roles()
                tenant_role_keys = [role.key for role in all_roles if role.group == tenant_group]

                try:
                    await self.project_provider.create_project_grant(
                        org_id, self.ucp_project_id, tenant_role_keys
                    )
                    grant_succeeded = True
                except Exception as error:
                    logger.error(
                        f"Failed to grant UCP project to org {org_id}. "
                        "The organization was created successfully but project grant failed. "
                        f"Manual intervention or retry may be required: {error}"
                    )

            return org_id, grant_succeeded
        except Exception as error:
            logger.error(f"Error creating organization in Zitadel: {error}")
            raise error

    async def delete_organization(self, org_id: str) -> None:
        logger.info(f"Deleting Organization in Zitadel: {org_id}")

        try:
            # First try admin v1 delete (which works cross-org)
            response = await self.fetch_with_auth(
                endpoint=f"/admin/v1/orgs/{org_id}", method="DELETE"
            )

            if response.status_code >= 400:
                # Fallback to management v1 if admin fails
                response = await self.fetch_with_auth(
                    endpoint=f"/management/v1/orgs/{org_id}", method="DELETE"
                )

            if response.status_code >= 400:
                await self.handle_response_error(response, "delete org")

            logger.info(f"Successfully deleted Organization {org_id} from Zitadel")
        except Exception as error:
            logger.error(f"Error deleting organization {org_id} in Zitadel: {error}")
            raise error
