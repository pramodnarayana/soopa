export interface UserData {
  id: string;
  email: string;
  name: string;
}

export interface TenantRepository {
  findUserByEmail(email: string): Promise<UserData | null>;
  provisionUserAndTenant(email: string, name: string, zitadelOrgId?: string): Promise<{ userId: string, tenantId: string }>;
  getTenantMappingForUser(userId: string): Promise<string | null>;
}
