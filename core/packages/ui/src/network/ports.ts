export const ApiErrorCode = {
  BAD_REQUEST: 'BAD_REQUEST',
  UNAUTHORIZED: 'UNAUTHORIZED',
  FORBIDDEN: 'FORBIDDEN',
  NOT_FOUND: 'NOT_FOUND',
  CONFLICT: 'CONFLICT',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  RATE_LIMITED: 'RATE_LIMITED',
  SERVER_ERROR: 'SERVER_ERROR',
  NETWORK_ABORTED: 'NETWORK_ABORTED',
  NETWORK_FAILURE: 'NETWORK_FAILURE',
  SCHEMA_DRIFT: 'SCHEMA_DRIFT',
} as const;

export type ApiErrorCodeValue = (typeof ApiErrorCode)[keyof typeof ApiErrorCode];

export const HttpMethod = {
  GET: 'GET',
  POST: 'POST',
  PUT: 'PUT',
  PATCH: 'PATCH',
  DELETE: 'DELETE',
} as const;

export type HttpMethodValue = (typeof HttpMethod)[keyof typeof HttpMethod];

export type QueryParamScalar = string | number | boolean | null | undefined;
export type QueryParamsRecord = Readonly<Record<string, QueryParamScalar>>;

export interface ApiProblem {
  readonly code: ApiErrorCodeValue;
  readonly status: number;
  readonly message: string;
  readonly serverCode?: string;
  readonly correlationId?: string;
  readonly retryAfterSeconds?: number;
  readonly fieldErrors?: Readonly<Record<string, string>>;
}

export type Result<T, E = ApiProblem> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: E };

export function ok<T>(value: T): Result<T, never> {
  return { ok: true, value };
}

export function err<E>(error: E): Result<never, E> {
  return { ok: false, error };
}

/**
 * Explicit opt-in error wrapper used strictly by legacy TanStack Query boundaries
 * that require thrown errors rather than first-class Result values.
 */
export class ApiProblemError extends Error {
  public readonly problem: ApiProblem;
  public readonly statusCode: number;

  constructor(problem: ApiProblem) {
    super(problem.message);
    this.name = 'ApiProblemError';
    this.problem = problem;
    this.statusCode = problem.status;
  }
}

export function unwrapOrThrow<T>(result: Result<T, ApiProblem>): T {
  if (result.ok) {
    return result.value;
  }
  throw new ApiProblemError(result.error);
}

export interface HttpRequestOptions {
  readonly params?: QueryParamsRecord;
  readonly headers?: HeadersInit;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
  readonly idempotencyKey?: string;
}

export interface HttpClientPort {
  request<T>(
    method: HttpMethodValue,
    path: string,
    body?: unknown,
    options?: HttpRequestOptions,
  ): Promise<Result<T, ApiProblem>>;
  get<T>(path: string, options?: HttpRequestOptions): Promise<Result<T, ApiProblem>>;
  post<T>(
    path: string,
    body?: unknown,
    options?: HttpRequestOptions,
  ): Promise<Result<T, ApiProblem>>;
  put<T>(
    path: string,
    body?: unknown,
    options?: HttpRequestOptions,
  ): Promise<Result<T, ApiProblem>>;
  patch<T>(
    path: string,
    body?: unknown,
    options?: HttpRequestOptions,
  ): Promise<Result<T, ApiProblem>>;
  delete<T>(path: string, options?: HttpRequestOptions): Promise<Result<T, ApiProblem>>;
}
