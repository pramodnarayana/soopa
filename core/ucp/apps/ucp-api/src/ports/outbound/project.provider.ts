import { ZitadelRole, ZitadelUser } from '../../domain/dtos/zitadel.dto.js';

export const PROJECT_PROVIDER = Symbol('PROJECT_PROVIDER');

export interface IProjectProvider {
  createProjectGrant(
    orgId: string,
    projectId: string,
    roleKeys: string[],
  ): Promise<unknown>;
  deleteProjectGrant(orgId: string, projectId: string): Promise<void>;
  getRoles(): Promise<ZitadelRole[]>;
  getUsers(orgId: string): Promise<ZitadelUser[]>;
}
