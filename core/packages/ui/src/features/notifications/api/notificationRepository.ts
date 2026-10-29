import type { ApiProblem, HttpClientPort, Result } from '../../../network';

export const NotificationSeverity = {
  INFO: 'info',
  HIGH: 'high',
  URGENT: 'urgent',
} as const;

export type NotificationSeverityValue =
  (typeof NotificationSeverity)[keyof typeof NotificationSeverity];

export interface InAppNotification {
  readonly id: string;
  readonly title: string;
  readonly body: string;
  readonly severity: NotificationSeverityValue;
  readonly is_read: boolean;
  readonly created_at: string;
}

export interface NotificationRepositoryPort {
  listInApp(signal?: AbortSignal): Promise<Result<InAppNotification[], ApiProblem>>;
  markAsRead(notificationId: string): Promise<Result<void, ApiProblem>>;
}

/**
 * Platform-level HTTP repository for in-app notification inbox queries & read receipts.
 * Depends strictly on HttpClientPort via DI and returns Result<T, ApiProblem>.
 */
export class HttpNotificationRepository implements NotificationRepositoryPort {
  public constructor(
    private readonly httpClient: HttpClientPort,
    private readonly tenantId: string,
    private readonly userId: string,
  ) {}

  private get basePath(): string {
    return `/${encodeURIComponent(this.tenantId)}/users/${encodeURIComponent(this.userId)}/in-app`;
  }

  public listInApp(signal?: AbortSignal): Promise<Result<InAppNotification[], ApiProblem>> {
    return this.httpClient.get<InAppNotification[]>(this.basePath, { signal });
  }

  public markAsRead(notificationId: string): Promise<Result<void, ApiProblem>> {
    return this.httpClient.put<void>(`${this.basePath}/${encodeURIComponent(notificationId)}/read`);
  }
}
