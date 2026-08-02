export interface UserData {
  id: string;
  email: string;
  name: string;
}

export interface TenantRepository {
  findUserByEmail(email: string): Promise<UserData | null>;
  /**
   * Retrieves a user by their external IdP user ID (sub).
   * This is a read-only operation. JIT provisioning is an anti-pattern and should not be done here.
   */
  findUserByIdpId(idpUserId: string): Promise<UserData | null>;
  getTenantMappingForUser(userId: string): Promise<string | null>;
}
