export const APP_SUBSCRIPTION_REPOSITORY = Symbol('APP_SUBSCRIPTION_REPOSITORY');

export interface IAppSubscriptionRepository {
  getActiveAppSlugsForTenant(tenantId: string): Promise<string[]>;
}
