export const USER_IDENTITY_PROVIDER = Symbol('USER_IDENTITY_PROVIDER');

export interface IUserIdentityProvider {
  inviteUser(
    orgId: string,
    email: string,
    role: string,
    firstName: string,
    lastName: string,
  ): Promise<{ userId: string }>;
  updateUser(
    userId: string,
    orgId: string,
    firstName: string,
    lastName: string,
    role: string,
  ): Promise<void>;
  deleteUser(userId: string): Promise<void>;
  toggleUserStatus(
    userId: string,
    orgId: string,
    action: 'activate' | 'deactivate',
  ): Promise<void>;
}
