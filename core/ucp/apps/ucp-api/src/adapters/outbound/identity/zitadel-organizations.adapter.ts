import { Inject, Injectable } from '@nestjs/common';
import { z } from 'zod';
import type { IOrganizationProvider } from '../../../ports/outbound/organization.provider.js';
import type { IProjectProvider } from '../../../ports/outbound/project.provider.js';
import { PROJECT_PROVIDER } from '../../../ports/outbound/project.provider.js';
import { ZitadelBaseClient } from './zitadel-base.client.js';

const CreateOrgResponseSchema = z.object({
  id: z.string().optional(),
  organizationId: z.string().optional(),
  orgId: z.string().optional(),
});

@Injectable()
export class ZitadelOrganizationsAdapter
  extends ZitadelBaseClient
  implements IOrganizationProvider
{
  constructor(
    @Inject(PROJECT_PROVIDER)
    private readonly projectProvider: IProjectProvider,
  ) {
    super();
  }

  async createOrganization(
    name: string,
  ): Promise<{ orgId: string; grantSucceeded?: boolean }> {
    this.logger.log(`Provisioning Organization in Zitadel: ${name}`);

    try {
      const response = await this.fetchWithAuth('/management/v1/orgs', {
        method: 'POST',
        body: JSON.stringify({ name }),
      });

      if (!response.ok) {
        await this.handleResponseError(response, 'create org');
      }

      const data = (await response.json()) as unknown;
      const parsedData = CreateOrgResponseSchema.parse(data);
      const orgId =
        parsedData.id || parsedData.organizationId || parsedData.orgId;
      if (!orgId) throw new Error('Org ID not returned from Zitadel');
      this.logger.log(`Created Organization in Zitadel with ID: ${orgId}`);

      let grantSucceeded = false;
      if (this.ucpProjectId) {
        // Enterprise Grade: Dynamically query the source of truth (Zitadel Project)
        // for all roles assigned to the configured tenant group so we never have to hardcode role additions.
        const tenantGroup = process.env.ZITADEL_TENANT_ROLE_GROUP || 'Tenant';
        const allRoles = await this.projectProvider.getRoles();
        const tenantRoleKeys = allRoles
          .filter((role) => role.group === tenantGroup) // Groups are configured in main.tf
          .map((role) => role.key);

        try {
          await this.projectProvider.createProjectGrant(
            orgId,
            this.ucpProjectId,
            tenantRoleKeys,
          );
          grantSucceeded = true;
        } catch (error) {
          this.logger.error(
            `Failed to grant UCP project to org ${orgId}. The organization was created successfully but project grant failed. Manual intervention or retry may be required.`,
            error,
          );
          // Don't throw, let org creation succeed even if grant fails
          // Caller should check grantSucceeded and handle accordingly
        }
      }

      return { orgId, grantSucceeded };
    } catch (error) {
      this.logger.error('Error creating organization in Zitadel', error);
      throw error;
    }
  }

  async deleteOrganization(orgId: string): Promise<void> {
    this.logger.log(`Deleting Organization in Zitadel: ${orgId}`);

    try {
      // First try admin v1 delete (which works cross-org)
      let response = await this.fetchWithAuth(`/admin/v1/orgs/${orgId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        // Fallback to management v1 if admin fails
        response = await this.fetchWithAuth(`/management/v1/orgs/${orgId}`, {
          method: 'DELETE',
        });
      }

      if (!response.ok) {
        await this.handleResponseError(response, 'delete org');
      }

      this.logger.log(
        `Successfully deleted Organization ${orgId} from Zitadel`,
      );
    } catch (error) {
      this.logger.error(
        `Error deleting organization ${orgId} in Zitadel`,
        error,
      );
      throw error;
    }
  }
}
