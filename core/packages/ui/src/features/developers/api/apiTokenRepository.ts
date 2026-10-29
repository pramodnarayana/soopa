import type { ApiProblem, HttpClientPort, Result } from '../../../network';
import type { ApiToken, ApiTokenCreated, CreateApiTokenPayload } from '../types';

export interface ApiTokenRepositoryPort {
  getAll(signal?: AbortSignal): Promise<Result<ApiToken[], ApiProblem>>;
  create(payload: CreateApiTokenPayload): Promise<Result<ApiTokenCreated, ApiProblem>>;
  update(
    id: string,
    data: { readonly name?: string; readonly active?: boolean },
  ): Promise<Result<void, ApiProblem>>;
  delete(id: string): Promise<Result<void, ApiProblem>>;
}

/**
 * Platform-level HTTP repository for API Token CRUD operations.
 * Depends strictly on the abstract HttpClientPort (zero adapter-to-adapter coupling)
 * and returns structured Result<T, ApiProblem> values without throwing exceptions.
 */
export class HttpApiTokenRepository implements ApiTokenRepositoryPort {
  public constructor(
    private readonly httpClient: HttpClientPort,
    private readonly tenantId: string,
  ) {}

  private get basePath(): string {
    return `/tenants/${encodeURIComponent(this.tenantId)}/tokens`;
  }

  public getAll(signal?: AbortSignal): Promise<Result<ApiToken[], ApiProblem>> {
    return this.httpClient.get<ApiToken[]>(this.basePath, { signal });
  }

  public create(payload: CreateApiTokenPayload): Promise<Result<ApiTokenCreated, ApiProblem>> {
    return this.httpClient.post<ApiTokenCreated>(this.basePath, payload);
  }

  public update(
    id: string,
    data: { readonly name?: string; readonly active?: boolean },
  ): Promise<Result<void, ApiProblem>> {
    return this.httpClient.patch<void>(`${this.basePath}/${encodeURIComponent(id)}`, data);
  }

  public delete(id: string): Promise<Result<void, ApiProblem>> {
    return this.httpClient.delete<void>(`${this.basePath}/${encodeURIComponent(id)}`);
  }
}
