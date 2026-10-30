import type { ApiProblem, HttpClientPort, Result } from '../../../network';
import type { CreateWebhookPayload, UpdateWebhookPayload, Webhook } from '../types';

export interface WebhookRepositoryPort {
  getAll(signal?: AbortSignal): Promise<Result<Webhook[], ApiProblem>>;
  create(payload: CreateWebhookPayload): Promise<Result<Webhook, ApiProblem>>;
  update(id: string, payload: UpdateWebhookPayload): Promise<Result<Webhook, ApiProblem>>;
  delete(id: string): Promise<Result<void, ApiProblem>>;
}

/**
 * Platform-level HTTP repository for Webhook CRUD operations.
 * Depends strictly on the abstract HttpClientPort (zero adapter-to-adapter coupling)
 * and returns structured Result<T, ApiProblem> values without throwing exceptions.
 */
export class HttpWebhookRepository implements WebhookRepositoryPort {
  public constructor(
    private readonly httpClient: HttpClientPort,
    private readonly tenantId: string,
  ) {}

  private get basePath(): string {
    return `/tenants/${encodeURIComponent(this.tenantId)}/webhooks`;
  }

  public getAll(signal?: AbortSignal): Promise<Result<Webhook[], ApiProblem>> {
    return this.httpClient.get<Webhook[]>(this.basePath, { signal });
  }

  public create(payload: CreateWebhookPayload): Promise<Result<Webhook, ApiProblem>> {
    return this.httpClient.post<Webhook>(this.basePath, payload);
  }

  public update(id: string, payload: UpdateWebhookPayload): Promise<Result<Webhook, ApiProblem>> {
    return this.httpClient.patch<Webhook>(`${this.basePath}/${encodeURIComponent(id)}`, payload);
  }

  public delete(id: string): Promise<Result<void, ApiProblem>> {
    return this.httpClient.delete<void>(`${this.basePath}/${encodeURIComponent(id)}`);
  }
}
