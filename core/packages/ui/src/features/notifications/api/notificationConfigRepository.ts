import type { ApiProblem, HttpClientPort, Result } from '../../../network';

export interface NotificationPreference {
  readonly id: string;
  readonly tenant_id: string;
  readonly event_type: string;
  readonly channels: string[];
}

export interface NotificationTemplate {
  readonly id: string;
  readonly tenant_id: string;
  readonly name: string;
  readonly event_type: string;
  readonly channel: string;
  readonly subject_template: string | null;
  readonly body_template: string;
  readonly is_active: boolean;
}

export interface PreviewResult {
  readonly rendered_subject: string | null;
  readonly rendered_body: string;
}

export type UpsertNotificationTemplateInput = Omit<NotificationTemplate, 'id' | 'tenant_id'>;

export interface PreviewNotificationTemplateInput {
  readonly body_template: string;
  readonly subject_template?: string;
  readonly mock_payload?: Record<string, unknown>;
}

export interface NotificationConfigRepositoryPort {
  listPreferences(signal?: AbortSignal): Promise<Result<NotificationPreference[], ApiProblem>>;
  upsertPreference(
    eventType: string,
    channels: readonly string[],
  ): Promise<Result<NotificationPreference, ApiProblem>>;
  deletePreference(eventType: string): Promise<Result<void, ApiProblem>>;
  listTemplates(signal?: AbortSignal): Promise<Result<NotificationTemplate[], ApiProblem>>;
  upsertTemplate(
    payload: UpsertNotificationTemplateInput,
  ): Promise<Result<NotificationTemplate, ApiProblem>>;
  deleteTemplate(templateId: string): Promise<Result<void, ApiProblem>>;
  previewTemplate(
    payload: PreviewNotificationTemplateInput,
  ): Promise<Result<PreviewResult, ApiProblem>>;
}

/**
 * Platform-level HTTP repository for tenant Notification Preferences & Jinja2 Templates.
 * Depends strictly on HttpClientPort via DI and returns Result<T, ApiProblem>.
 */
export class HttpNotificationConfigRepository implements NotificationConfigRepositoryPort {
  public constructor(
    private readonly httpClient: HttpClientPort,
    private readonly tenantId: string,
  ) {}

  private get basePath(): string {
    return `/${encodeURIComponent(this.tenantId)}`;
  }

  public listPreferences(
    signal?: AbortSignal,
  ): Promise<Result<NotificationPreference[], ApiProblem>> {
    return this.httpClient.get<NotificationPreference[]>(`${this.basePath}/preferences`, {
      signal,
    });
  }

  public upsertPreference(
    eventType: string,
    channels: readonly string[],
  ): Promise<Result<NotificationPreference, ApiProblem>> {
    return this.httpClient.put<NotificationPreference>(
      `${this.basePath}/preferences/${encodeURIComponent(eventType)}`,
      { channels },
    );
  }

  public deletePreference(eventType: string): Promise<Result<void, ApiProblem>> {
    return this.httpClient.delete<void>(
      `${this.basePath}/preferences/${encodeURIComponent(eventType)}`,
    );
  }

  public listTemplates(signal?: AbortSignal): Promise<Result<NotificationTemplate[], ApiProblem>> {
    return this.httpClient.get<NotificationTemplate[]>(`${this.basePath}/templates`, { signal });
  }

  public upsertTemplate(
    payload: UpsertNotificationTemplateInput,
  ): Promise<Result<NotificationTemplate, ApiProblem>> {
    return this.httpClient.put<NotificationTemplate>(`${this.basePath}/templates`, payload);
  }

  public deleteTemplate(templateId: string): Promise<Result<void, ApiProblem>> {
    return this.httpClient.delete<void>(
      `${this.basePath}/templates/${encodeURIComponent(templateId)}`,
    );
  }

  public previewTemplate(
    payload: PreviewNotificationTemplateInput,
  ): Promise<Result<PreviewResult, ApiProblem>> {
    return this.httpClient.post<PreviewResult>(`${this.basePath}/templates/preview`, payload);
  }
}
