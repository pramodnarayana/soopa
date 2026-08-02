export const TARGET_CONTROL_PLANE_OUTBOX_REPOSITORY = Symbol(
  'TARGET_CONTROL_PLANE_OUTBOX_REPOSITORY',
);

export interface ITargetControlPlaneOutboxRepository {
  publishToApp<T extends Record<string, unknown>>(
    appSlug: string,
    event: {
      id: string;
      tenantId: string | null;
      eventType: string;
      payload: T;
    },
  ): Promise<void>;
}
