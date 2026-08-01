export const USER_REPOSITORY = Symbol('USER_REPOSITORY');

export interface IUserRepository {
  upsertUser(user: {
    id: string;
    idpUserId?: string;
    email?: string;
    name: string;
  }): Promise<void>;
  findByIdpUserId(idpUserId: string): Promise<{
    id: string;
    idpUserId: string | null;
    email: string;
    name: string;
  } | null>;
  findByEmail(email: string): Promise<{
    id: string;
    idpUserId: string | null;
    email: string;
    name: string;
  } | null>;
  upsertTenantUser(tenantUser: {
    tenantId: string;
    userId: string;
    role: string;
  }): Promise<void>;
  removeTenantUser(tenantId: string, userId: string): Promise<void>;
  findUsersByTenant(tenantId: string): Promise<
    {
      id: string;
      idpUserId: string | null;
      email: string;
      name: string;
      role: string;
      createdAt: Date;
    }[]
  >;
  deleteOrphanedUsers(userIds: string[]): Promise<void>;
}
