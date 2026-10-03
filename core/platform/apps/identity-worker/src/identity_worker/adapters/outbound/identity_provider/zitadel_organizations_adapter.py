import structlog
from identity.adapters.outbound.zitadel.client import ZitadelClient
from identity.adapters.outbound.zitadel.exceptions import ZitadelHttpError, ZitadelHttpNotFoundError
from pydantic import BaseModel, Field

from identity_worker.config.settings import AppSettings
from identity_worker.domain.exceptions import IdentityProviderPortError
from identity_worker.ports.outbound.organization_provider_port import OrganizationProviderPort
from identity_worker.ports.outbound.project_provider_port import ProjectProviderPort

logger = structlog.get_logger(__name__)


class CreateOrgResponse(BaseModel):
    id: str | None = None
    organization_id: str | None = Field(None, alias="organizationId")
    org_id: str | None = Field(None, alias="orgId")


class ZitadelOrganizationsAdapter(ZitadelClient, OrganizationProviderPort):
    def __init__(self, project_provider: ProjectProviderPort, settings: AppSettings) -> None:
        super().__init__(
            api_url=settings.zitadel_api_url,
            machine_key=settings.zitadel_machine_key,
            ucp_project_id=settings.zitadel_ucp_project_id,
            default_user_password=settings.zitadel_default_user_password,
        )
        self.project_provider = project_provider
        self.settings = settings

    async def create_organization(self, tenant_id: str, name: str) -> tuple[str, bool]:
        logger.info("provisioning_organization_in_zitadel", org_name=name, tenant_id=tenant_id)
        org_id = await self._create_or_recover_organization(tenant_id, name)

        grant_succeeded = False
        if self.ucp_project_id:
            grant_succeeded = await self._grant_ucp_project(org_id, name)

        return org_id, grant_succeeded

    async def _create_or_recover_organization(self, tenant_id: str, name: str) -> str:
        try:
            response = await self.fetch_with_auth(
                endpoint="/v2/organizations",
                method="POST",
                json={"organizationId": tenant_id, "name": name},
            )

            data = response.json()
            parsed_data = CreateOrgResponse.model_validate(data)
            org_id = (
                parsed_data.id or parsed_data.organization_id or parsed_data.org_id or tenant_id
            )

            if not org_id:
                raise ValueError("Org ID not returned from Zitadel")

            logger.info("created_organization_in_zitadel", org_id=org_id)
            return org_id

        except ZitadelHttpError as e:
            if e.status_code == 409:
                return await self._recover_existing_organization(tenant_id, name)
            logger.exception("error_creating_organization_in_zitadel", org_name=name)
            raise IdentityProviderPortError("Failed to create organization") from e
        except IdentityProviderPortError:
            raise
        except Exception as e:
            logger.exception("error_creating_organization_in_zitadel", org_name=name)
            raise IdentityProviderPortError("Failed to create organization") from e

    async def _recover_existing_organization(self, tenant_id: str, name: str) -> str:
        logger.warning(
            "organization_already_exists_attempting_deterministic_recovery",
            org_id=tenant_id,
            org_name=name,
        )
        try:
            # Deterministic idempotency: verify if the org exists with OUR specific UUID
            org_response = await self.fetch_with_auth(
                endpoint=f"/admin/v1/orgs/{tenant_id}", method="GET"
            )
            org_data = org_response.json()
            recovered_id = org_data.get("org", {}).get("id") or tenant_id
            logger.info("recovered_existing_organization_from_zitadel", org_id=recovered_id)
            return recovered_id
        except ZitadelHttpNotFoundError:
            logger.exception(
                "genuine_duplicate_organization_name",
                org_name=name,
            )
            raise IdentityProviderPortError(
                f"Organization name '{name}' is already taken by another tenant."
            )
        except Exception as search_err:
            logger.exception(
                "failed_to_recover_existing_organization", org_name=name, org_id=tenant_id
            )
            raise IdentityProviderPortError(
                "Failed to recover existing organization"
            ) from search_err

    async def _grant_ucp_project(self, org_id: str, name: str) -> bool:
        try:
            tenant_group = self.settings.zitadel_tenant_role_group
            all_roles = await self.project_provider.get_roles()
            tenant_role_keys = [role.key for role in all_roles if role.group == tenant_group]

            try:
                await self.project_provider.create_project_grant(
                    org_id, self.ucp_project_id, tenant_role_keys
                )
                return True
            except ZitadelHttpError as grant_e:
                if grant_e.status_code == 409:
                    logger.info("project_grant_already_exists", org_id=org_id)
                    return True
                raise
            except Exception as e:
                logger.exception(
                    "failed_to_grant_ucp_project_to_org",
                    org_id=org_id,
                )
                raise IdentityProviderPortError(
                    "Failed to grant UCP project to organization"
                ) from e
        except IdentityProviderPortError:
            raise
        except Exception as e:
            logger.exception("error_granting_project_to_organization", org_name=name)
            raise IdentityProviderPortError("Failed to grant project to organization") from e

    async def grant_project_to_organization(self, org_id: str, project_id: str) -> None:
        logger.info("granting_project_to_organization", org_id=org_id, project_id=project_id)
        tenant_group = self.settings.zitadel_tenant_role_group
        all_roles = await self.project_provider.get_roles(project_id)
        tenant_role_keys = [role.key for role in all_roles if role.group == tenant_group]

        try:
            await self.project_provider.create_project_grant(org_id, project_id, tenant_role_keys)
            logger.info("project_granted_to_organization", org_id=org_id, project_id=project_id)
        except Exception as e:
            logger.exception(
                "error_granting_project_to_organization", org_id=org_id, project_id=project_id
            )
            raise IdentityProviderPortError("Failed to grant project to organization") from e

    async def revoke_project_from_organization(self, org_id: str, project_id: str) -> None:
        logger.info("revoking_project_from_organization", org_id=org_id, project_id=project_id)
        try:
            await self.project_provider.delete_project_grant(org_id, project_id)
            logger.info("project_revoked_from_organization", org_id=org_id, project_id=project_id)
        except Exception as e:
            logger.exception(
                "error_revoking_project_from_organization", org_id=org_id, project_id=project_id
            )
            raise IdentityProviderPortError("Failed to revoke project from organization") from e

    async def delete_organization(self, org_id: str) -> None:
        logger.info("deleting_organization_in_zitadel", org_id=org_id)

        try:
            # First try admin v1 delete (which works cross-org)
            try:
                await self.fetch_with_auth(endpoint=f"/admin/v1/orgs/{org_id}", method="DELETE")
            except ZitadelHttpError:
                # Fallback to management v1 if admin fails — even a 404 should still
                # proceed to the management fallback, just in case.
                await self.fetch_with_auth(
                    endpoint=f"/management/v1/orgs/{org_id}", method="DELETE"
                )

            logger.info("successfully_deleted_organization_from_zitadel", org_id=org_id)
        except ZitadelHttpNotFoundError:
            logger.info("organization_already_deleted", org_id=org_id)
        except Exception as e:
            logger.exception("error_deleting_organization_in_zitadel", org_id=org_id)
            raise IdentityProviderPortError("Failed to delete organization") from e

    async def update_organization_name(self, org_id: str, name: str) -> None:
        logger.info("updating_organization_name_in_zitadel", org_id=org_id, org_name=name)

        try:
            await self.fetch_with_auth(
                endpoint="/management/v1/orgs/me",
                method="PUT",
                headers={"x-zitadel-orgid": org_id},
                json={"name": name},
            )

            logger.info("successfully_updated_organization_name_in_zitadel", org_id=org_id)
        except Exception as e:
            logger.exception("error_updating_organization_name_in_zitadel", org_id=org_id)
            raise IdentityProviderPortError("Failed to update organization name") from e

    async def toggle_organization_status(self, org_id: str, active: bool) -> None:
        logger.info("toggling_organization_status_in_zitadel", org_id=org_id, active=active)

        try:
            endpoint = f"/management/v1/orgs/me/_{'reactivate' if active else 'deactivate'}"
            await self.fetch_with_auth(
                endpoint=endpoint,
                method="POST",
                headers={"x-zitadel-orgid": org_id},
                json={},
            )

            logger.info(
                "successfully_toggled_organization_status_in_zitadel", org_id=org_id, active=active
            )
        except Exception as e:
            logger.exception("error_toggling_organization_status_in_zitadel", org_id=org_id)
            raise IdentityProviderPortError("Failed to toggle organization status") from e
