import { Injectable, HttpException, HttpStatus } from '@nestjs/common';
import {
  ZitadelProjectGrantsResponseSchema,
  ZitadelUserSchema,
} from '../../../domain/dtos/zitadel.dto';
import { IUserIdentityProvider } from '../../../ports/outbound/user-identity.provider';
import { ZitadelBaseClient } from './zitadel-base.client';

@Injectable()
export class ZitadelUsersAdapter
  extends ZitadelBaseClient
  implements IUserIdentityProvider
{
  async inviteUser(
    orgId: string,
    email: string,
    role: string,
    firstName: string,
    lastName: string,
  ): Promise<{ userId: string }> {
    this.logger.log(`Creating user ${email} in org ${orgId} with role ${role}`);

    try {
      // 1. Create Human User in the specific Organization
      const userRes = await this.fetchWithAuth('/management/v1/users/human', {
        method: 'POST',
        headers: {
          'x-zitadel-orgid': orgId,
        },
        body: JSON.stringify({
          userName: email,
          profile: {
            firstName: firstName,
            lastName: lastName,
            displayName: `${firstName} ${lastName}`,
            preferredLanguage: 'en',
          },
          email: {
            email: email,
            isEmailVerified: true,
          },
          initialPassword: 'TenantUser123!',
        }),
      });

      if (!userRes.ok) await this.handleResponseError(userRes, 'create user');

      const data = (await userRes.json()) as unknown;
      const userData = ZitadelUserSchema.parse(data);
      const userId = userData.userId || userData.id;
      if (!userId) {
        throw new Error('User ID not returned from Zitadel');
      }
      this.logger.log(`Created User ${userId} in Org ${orgId}`);

      // 2. Fetch the Project Grant ID for the UCP Project to this Org
      const grantSearchRes = await this.fetchWithAuth(
        `/management/v1/projects/${this.ucpProjectId}/grants/_search`,
        {
          method: 'POST',
          body: JSON.stringify({ queries: [] }),
        },
      );

      if (!grantSearchRes.ok)
        await this.handleResponseError(grantSearchRes, 'fetch project grants');

      const grantSearchData = (await grantSearchRes.json()) as unknown;
      const parsedGrantData =
        ZitadelProjectGrantsResponseSchema.parse(grantSearchData);
      const projectGrant = parsedGrantData.result?.find(
        (g) => g.grantedOrgId === orgId,
      );

      if (!projectGrant) {
        this.logger.warn(
          `No UCP project grant found for org ${orgId}, skipping role assignment for user ${userId}`,
        );
        return { userId };
      }

      const grantId = projectGrant.grantId || projectGrant.id;

      // 3. Grant the Role to the User on the Project Grant
      this.logger.log(
        `Assigning role [${role}] to user ${userId} via Project Grant ${grantId}`,
      );
      const userGrantRes = await this.fetchWithAuth(
        `/management/v1/users/${userId}/grants`,
        {
          method: 'POST',
          headers: {
            'x-zitadel-orgid': orgId,
          },
          body: JSON.stringify({
            projectId: this.ucpProjectId,
            projectGrantId: grantId,
            roleKeys: [role],
          }),
        },
      );

      if (!userGrantRes.ok) {
        const errorText = await userGrantRes.text();
        this.logger.error(`Failed to assign role to user: ${errorText}`);
      }

      return { userId };
    } catch (error) {
      this.logger.error(`Error creating user ${email} in org ${orgId}`, error);
      throw error;
    }
  }

  async updateUser(
    userId: string,
    orgId: string,
    firstName: string,
    lastName: string,
    role: string,
  ): Promise<void> {
    this.logger.log(`Updating user ${userId} in org ${orgId}`);

    try {
      // 1. Update profile
      const profileRes = await this.fetchWithAuth(
        `/management/v1/users/${userId}/profile`,
        {
          method: 'PUT',
          headers: {
            'x-zitadel-orgid': orgId,
          },
          body: JSON.stringify({
            firstName,
            lastName,
            displayName: `${firstName} ${lastName}`,
            preferredLanguage: 'en',
          }),
        },
      );

      if (!profileRes.ok) {
        const err = await profileRes.text();
        if (!err.includes('Profile not changed')) {
          this.logger.error(`Failed to update user profile: ${err}`);
          throw new HttpException(
            `Failed to update user profile: ${err}`,
            HttpStatus.INTERNAL_SERVER_ERROR,
          );
        }
      }

      // 2. Update role
      const grantsRes = await this.fetchWithAuth(
        `/management/v1/users/grants/_search`,
        {
          method: 'POST',
          headers: {
            'x-zitadel-orgid': orgId,
          },
          body: JSON.stringify({ queries: [{ userIdQuery: { userId } }] }),
        },
      );

      if (grantsRes.ok) {
        const grantsData = (await grantsRes.json()) as unknown;
        const parsedGrantsData =
          ZitadelProjectGrantsResponseSchema.parse(grantsData);
        const grant = parsedGrantsData.result?.find(
          (g) => g.projectId === this.ucpProjectId,
        );
        if (grant) {
          const updateGrantRes = await this.fetchWithAuth(
            `/management/v1/users/${userId}/grants/${grant.id}`,
            {
              method: 'PUT',
              headers: {
                'x-zitadel-orgid': orgId,
              },
              body: JSON.stringify({ roleKeys: [role] }),
            },
          );
          if (!updateGrantRes.ok)
            await this.handleResponseError(updateGrantRes, 'update user grant');
        } else {
          // Create new grant fallback logic
          const grantSearchRes = await this.fetchWithAuth(
            `/management/v1/projects/${this.ucpProjectId}/grants/_search`,
            {
              method: 'POST',
              body: JSON.stringify({ queries: [] }),
            },
          );

          if (!grantSearchRes.ok)
            await this.handleResponseError(
              grantSearchRes,
              'fetch project grants fallback',
            );

          const grantSearchData = (await grantSearchRes.json()) as unknown;
          const parsedGrantSearchData =
            ZitadelProjectGrantsResponseSchema.parse(grantSearchData);
          const projectGrant = parsedGrantSearchData.result?.find(
            (g) => g.grantedOrgId === orgId,
          );

          if (projectGrant) {
            const projectGrantId = projectGrant.grantId || projectGrant.id;
            const createGrantRes = await this.fetchWithAuth(
              `/management/v1/users/${userId}/grants`,
              {
                method: 'POST',
                headers: {
                  'x-zitadel-orgid': orgId,
                },
                body: JSON.stringify({
                  projectId: this.ucpProjectId,
                  projectGrantId,
                  roleKeys: [role],
                }),
              },
            );
            if (!createGrantRes.ok)
              await this.handleResponseError(
                createGrantRes,
                'create user grant fallback',
              );
          } else {
            throw new HttpException(
              'No project grant found for this tenant',
              HttpStatus.INTERNAL_SERVER_ERROR,
            );
          }
        }
      } else {
        await this.handleResponseError(grantsRes, 'fetch user grants');
      }
    } catch (error) {
      this.logger.error(`Error updating user ${userId} in org ${orgId}`, error);
      throw error;
    }
  }

  async deleteUser(userId: string): Promise<void> {
    this.logger.log(`Deleting user ${userId} from Zitadel`);

    const response = await this.fetchWithAuth(
      `/management/v1/users/${userId}`,
      {
        method: 'DELETE',
      },
    );

    if (!response.ok) await this.handleResponseError(response, 'delete user');
  }

  async toggleUserStatus(
    userId: string,
    orgId: string,
    action: 'activate' | 'deactivate',
  ): Promise<void> {
    this.logger.log(`Toggling user ${userId} status: ${action}`);

    const endpoint = action === 'activate' ? 'activate' : 'deactivate';
    const response = await this.fetchWithAuth(
      `/management/v1/users/${userId}/${endpoint}`,
      {
        method: 'POST',
        headers: {
          'x-zitadel-orgid': orgId,
        },
      },
    );

    if (!response.ok)
      await this.handleResponseError(response, `${action} user`);
  }
}
