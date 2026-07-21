import { Injectable } from '@nestjs/common';
import { ZitadelBaseClient } from './zitadel-base.client';
import { IProjectProvider } from '../../../ports/outbound/project.provider';
import {
  ZitadelRolesResponseSchema,
  ZitadelProjectGrantsResponseSchema,
  ZitadelRawUserSearchResponseSchema,
} from '../../../domain/dtos/zitadel.dto';

@Injectable()
export class ZitadelProjectsAdapter
  extends ZitadelBaseClient
  implements IProjectProvider
{
  async createProjectGrant(
    orgId: string,
    projectId: string,
    roleKeys: string[],
  ): Promise<void> {
    this.logger.log(
      `Creating project grant in Zitadel. OrgId: ${orgId}, ProjectId: ${projectId}`,
    );

    try {
      const grantResponse = await this.fetchWithAuth(
        `/management/v1/projects/${projectId}/grants`,
        {
          method: 'POST',
          body: JSON.stringify({
            grantedOrgId: orgId,
            roleKeys: roleKeys,
          }),
        },
      );

      if (!grantResponse.ok)
        await this.handleResponseError(grantResponse, 'create project grant');

      this.logger.log(
        `Successfully granted Project ${projectId} to Organization ${orgId}`,
      );
    } catch (error) {
      this.logger.error(`Error creating project grant for org ${orgId}`, error);
      throw error;
    }
  }

  async getRoles(): Promise<
    import('../../../domain/dtos/zitadel.dto').ZitadelRole[]
  > {
    this.logger.log('Fetching roles for UCP Project');

    const response = await this.fetchWithAuth(
      `/management/v1/projects/${this.ucpProjectId}/roles/_search`,
      {
        method: 'POST',
        body: JSON.stringify({}),
      },
    );

    if (!response.ok) await this.handleResponseError(response, 'fetch roles');

    const data = (await response.json()) as unknown;
    const parsedData = ZitadelRolesResponseSchema.parse(data);
    return parsedData.result || [];
  }

  async getUsers(
    orgId: string,
  ): Promise<import('../../../domain/dtos/zitadel.dto').ZitadelUser[]> {
    this.logger.log(`Fetching users for org ${orgId}`);

    // 1. Fetch all users in the org
    const response = await this.fetchWithAuth('/management/v1/users/_search', {
      method: 'POST',
      headers: {
        'x-zitadel-orgid': orgId,
      },
      body: JSON.stringify({}),
    });

    if (!response.ok) await this.handleResponseError(response, 'fetch users');

    const data = (await response.json()) as unknown;
    const rawUsersData = ZitadelRawUserSearchResponseSchema.parse(data);
    const users = rawUsersData.result;

    // 2. Fetch grants for each user individually
    const usersWithRoles = await Promise.all(
      users.map(async (u) => {
        let role = 'Unknown';
        try {
          const grantRes = await this.fetchWithAuth(
            '/management/v1/users/grants/_search',
            {
              method: 'POST',
              headers: {
                'x-zitadel-orgid': orgId,
              },
              body: JSON.stringify({
                queries: [{ userIdQuery: { userId: u.id } }],
              }),
            },
          );
          if (grantRes.ok) {
            const grantData = (await grantRes.json()) as unknown;
            const parsedGrantData =
              ZitadelProjectGrantsResponseSchema.parse(grantData);
            const grant = parsedGrantData.result?.find(
              (g) => g.projectId === this.ucpProjectId,
            );
            if (grant?.roleKeys?.length) {
              role = grant.roleKeys[0];
            } else {
              role = 'Unknown';
            }
          }
        } catch {
          // leave role as Unknown if grant fetch fails
        }

        return {
          id: u.id,
          email: u.human?.email?.email || u.userName,
          displayName: u.human?.profile?.displayName || u.userName,
          firstName: u.human?.profile?.firstName,
          lastName: u.human?.profile?.lastName,
          state: u.state,
          role,
          createdAt: u.details?.creationDate,
        };
      }),
    );

    return usersWithRoles;
  }
}
