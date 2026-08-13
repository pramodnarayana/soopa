import structlog
from pydantic import BaseModel, Field

from ucp.adapters.outbound.identity.zitadel_client import ZitadelClient
from ucp.ports.outbound.organization_provider import IOrganizationProvider
from ucp.ports.outbound.project_provider import IProjectProvider

logger = structlog.get_logger(__name__)


class CreateOrgResponse(BaseModel):
    id: str | None = None
    organization_id: str | None = Field(None, alias="organizationId")
    org_id: str | None = Field(None, alias="orgId")


class ZitadelOrganizationsAdapter(ZitadelClient, IOrganizationProvider):
    def __init__(self, project_provider: IProjectProvider) -> None:
        super().__init__()
        self.project_provider = project_provider

    async def create_organization(self, name: str) -> tuple[str, bool]:
        logger.info("provisioning_organization_in_zitadel", org_name=name)

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

            logger.info("created_organization_in_zitadel", org_id=org_id)

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
                except Exception:
                    logger.exception(
                        "failed_to_grant_ucp_project_to_org",
                        org_id=org_id,
                        note="org_created_but_project_grant_failed_manual_intervention_required",
                    )

            return org_id, grant_succeeded
        except Exception:
            logger.exception("error_creating_organization_in_zitadel", org_name=name)

            raise

    async def delete_organization(self, org_id: str) -> None:
        logger.info("deleting_organization_in_zitadel", org_id=org_id)

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

            logger.info("successfully_deleted_organization_from_zitadel", org_id=org_id)
        except Exception:
            logger.exception("error_deleting_organization_in_zitadel", org_id=org_id)

            raise

    async def update_organization_name(self, org_id: str, name: str) -> None:
        logger.info("updating_organization_name_in_zitadel", org_id=org_id, org_name=name)

        try:
            response = await self.fetch_with_auth(
                endpoint=f"/v2/organizations/{org_id}", method="POST", json={"name": name}
            )

            if response.status_code >= 400:
                await self.handle_response_error(response, "update org name")

            logger.info("successfully_updated_organization_name_in_zitadel", org_id=org_id)
        except Exception:
            logger.exception("error_updating_organization_name_in_zitadel", org_id=org_id)
            raise

    async def toggle_organization_status(self, org_id: str, active: bool) -> None:
        logger.info("toggling_organization_status_in_zitadel", org_id=org_id, active=active)

        try:
            endpoint = f"/v2/organizations/{org_id}/{'activate' if active else 'deactivate'}"
            response = await self.fetch_with_auth(endpoint=endpoint, method="POST", json={})

            if response.status_code >= 400:
                await self.handle_response_error(response, "toggle org status")

            logger.info(
                "successfully_toggled_organization_status_in_zitadel", org_id=org_id, active=active
            )
        except Exception:
            logger.exception("error_toggling_organization_status_in_zitadel", org_id=org_id)
            raise
