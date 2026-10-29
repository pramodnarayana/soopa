import type { FrontendLoggerPort } from '../observability';
import {
  ApiErrorCode,
  type ApiErrorCodeValue,
  type ApiProblem,
  err,
  type HttpClientPort,
  HttpMethod,
  type HttpMethodValue,
  type HttpRequestOptions,
  ok,
  type QueryParamsRecord,
  type Result,
} from './ports';

const DEFAULT_TIMEOUT_MS = 15_000;
const MUTATING_METHODS: ReadonlySet<HttpMethodValue> = new Set([
  HttpMethod.POST,
  HttpMethod.PUT,
  HttpMethod.PATCH,
  HttpMethod.DELETE,
]);

export interface FetchHttpClientConfig {
  readonly baseUrl: string;
  readonly getToken?: () => string | null | undefined;
  readonly fetchImpl?: typeof fetch;
  readonly defaultTimeoutMs?: number;
  readonly logger?: FrontendLoggerPort;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function buildQueryString(params: QueryParamsRecord | undefined): string {
  if (!params) {
    return '';
  }
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  }
  return searchParams.toString();
}

function buildRequestUrl(baseUrl: string, path: string, params?: QueryParamsRecord): string {
  const normalizedBase = baseUrl.replace(/\/+$/, '');
  const normalizedPath = path.replace(/^\/+/, '');
  const fullPath = normalizedPath ? `${normalizedBase}/${normalizedPath}` : normalizedBase;
  const queryString = buildQueryString(params);
  if (!queryString) {
    return fullPath;
  }
  const separator = fullPath.includes('?') ? '&' : '?';
  return `${fullPath}${separator}${queryString}`;
}

function buildRequestHeaders(
  method: HttpMethodValue,
  hasBody: boolean,
  token: string | null | undefined,
  options: HttpRequestOptions | undefined,
): Headers {
  const headers = new Headers(options?.headers);
  if (hasBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (options?.idempotencyKey) {
    headers.set('Idempotency-Key', options.idempotencyKey);
  } else if (MUTATING_METHODS.has(method) && !headers.has('Idempotency-Key')) {
    headers.set('Idempotency-Key', crypto.randomUUID());
  }
  return headers;
}

function createAbortExecutionContext(
  callerSignal: AbortSignal | undefined,
  timeoutMs: number,
): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  if (!callerSignal) {
    return {
      signal: controller.signal,
      cleanup: () => clearTimeout(timeoutId),
    };
  }

  if (callerSignal.aborted) {
    controller.abort();
  }

  const onCallerAbort = (): void => controller.abort();
  callerSignal.addEventListener('abort', onCallerAbort, { once: true });

  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timeoutId);
      callerSignal.removeEventListener('abort', onCallerAbort);
    },
  };
}

function mapStatusToErrorCode(status: number): ApiErrorCodeValue {
  if (status === 400) return ApiErrorCode.BAD_REQUEST;
  if (status === 401) return ApiErrorCode.UNAUTHORIZED;
  if (status === 403) return ApiErrorCode.FORBIDDEN;
  if (status === 404) return ApiErrorCode.NOT_FOUND;
  if (status === 409) return ApiErrorCode.CONFLICT;
  if (status === 422) return ApiErrorCode.VALIDATION_ERROR;
  if (status === 429) return ApiErrorCode.RATE_LIMITED;
  return status >= 500 ? ApiErrorCode.SERVER_ERROR : ApiErrorCode.BAD_REQUEST;
}

function parseRetryAfterHeader(headers: Headers): number | undefined {
  const raw = headers.get('Retry-After');
  if (!raw) {
    return undefined;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function extractValidationFieldErrors(
  detail: unknown,
): Readonly<Record<string, string>> | undefined {
  if (!Array.isArray(detail)) {
    return undefined;
  }
  const errors: Record<string, string> = {};
  for (const item of detail) {
    if (!isPlainRecord(item) || typeof item.msg !== 'string') {
      continue;
    }
    const loc = Array.isArray(item.loc) ? item.loc : [];
    const lastSegment = loc.length > 0 ? String(loc[loc.length - 1]) : 'payload';
    errors[lastSegment] = item.msg;
  }
  return Object.keys(errors).length > 0 ? errors : undefined;
}

function extractMessageFromParsedJson(parsed: Record<string, unknown>, fallback: string): string {
  if (typeof parsed.message === 'string' && parsed.message.length > 0) {
    return parsed.message;
  }
  if (Array.isArray(parsed.message) && typeof parsed.message[0] === 'string') {
    return parsed.message[0];
  }
  if (typeof parsed.detail === 'string' && parsed.detail.length > 0) {
    return parsed.detail;
  }
  if (isPlainRecord(parsed.detail) && typeof parsed.detail.message === 'string') {
    return parsed.detail.message;
  }
  return fallback;
}

function extractServerCode(parsed: Record<string, unknown>): string | undefined {
  if (typeof parsed.error_code === 'string') {
    return parsed.error_code;
  }
  if (isPlainRecord(parsed.detail) && typeof parsed.detail.error_code === 'string') {
    return parsed.detail.error_code;
  }
  return undefined;
}

async function parseErrorProblem(response: Response): Promise<ApiProblem> {
  const fallback = response.statusText || `HTTP ${response.status}`;
  const rawText = await response.text();
  let message = fallback;
  let serverCode: string | undefined;
  let fieldErrors: Readonly<Record<string, string>> | undefined;

  if (rawText) {
    try {
      const parsed: unknown = JSON.parse(rawText);
      if (isPlainRecord(parsed)) {
        message = extractMessageFromParsedJson(parsed, fallback);
        serverCode = extractServerCode(parsed);
        fieldErrors = extractValidationFieldErrors(parsed.detail);
      }
    } catch {
      message = rawText;
    }
  }

  return {
    code: mapStatusToErrorCode(response.status),
    status: response.status,
    serverCode,
    message,
    correlationId: response.headers.get('X-Correlation-ID') ?? undefined,
    retryAfterSeconds: parseRetryAfterHeader(response.headers),
    fieldErrors,
  };
}

async function parseSuccessPayload<T>(response: Response): Promise<Result<T, ApiProblem>> {
  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return ok(undefined as T);
  }
  const rawText = await response.text();
  if (!rawText) {
    return ok(undefined as T);
  }
  try {
    return ok(JSON.parse(rawText) as T);
  } catch {
    return err({
      code: ApiErrorCode.SCHEMA_DRIFT,
      status: response.status,
      message: 'Expected valid JSON response body from server',
    });
  }
}

function mapTransportFailure(caught: unknown): ApiProblem {
  const isAbort =
    (caught instanceof DOMException && caught.name === 'AbortError') ||
    (caught instanceof Error && caught.name === 'AbortError');
  if (isAbort) {
    return {
      code: ApiErrorCode.NETWORK_ABORTED,
      status: 0,
      message: 'Network request was cancelled or timed out',
    };
  }
  return {
    code: ApiErrorCode.NETWORK_FAILURE,
    status: 0,
    message: caught instanceof Error ? caught.message : 'Network transport failure',
  };
}

function emitProblemTelemetry(
  logger: FrontendLoggerPort | undefined,
  method: HttpMethodValue,
  path: string,
  problem: ApiProblem,
  durationMs: number,
): void {
  if (!logger) {
    return;
  }
  const attrs = {
    method,
    path,
    status: problem.status,
    error_code: problem.code,
    server_code: problem.serverCode,
    correlation_id: problem.correlationId,
    retry_after_seconds: problem.retryAfterSeconds,
    duration_ms: durationMs,
  };
  if (problem.code === ApiErrorCode.NETWORK_ABORTED) {
    logger.warn('http_request.aborted', attrs);
    return;
  }
  logger.error('http_request.failed', attrs);
}

export class FetchHttpClientAdapter implements HttpClientPort {
  private readonly baseUrl: string;
  private readonly getToken?: () => string | null | undefined;
  private readonly fetchImpl: typeof fetch;
  private readonly defaultTimeoutMs: number;
  private readonly logger?: FrontendLoggerPort;

  constructor(config: FetchHttpClientConfig) {
    this.baseUrl = config.baseUrl;
    this.getToken = config.getToken;
    this.fetchImpl = config.fetchImpl ?? ((input, init) => fetch(input, init));
    this.defaultTimeoutMs = config.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.logger = config.logger;
  }

  private async executeAndClassify<T>(
    method: HttpMethodValue,
    path: string,
    url: string,
    headers: Headers,
    body: unknown,
    signal: AbortSignal,
    startedAt: number,
  ): Promise<Result<T, ApiProblem>> {
    const hasBody = body !== undefined;
    const response = await this.fetchImpl(url, {
      method,
      headers,
      body: hasBody ? JSON.stringify(body) : undefined,
      signal,
    });

    if (!response.ok) {
      const problem = await parseErrorProblem(response);
      emitProblemTelemetry(this.logger, method, path, problem, Date.now() - startedAt);
      return err(problem);
    }

    const parsed = await parseSuccessPayload<T>(response);
    if (!parsed.ok) {
      emitProblemTelemetry(this.logger, method, path, parsed.error, Date.now() - startedAt);
      return parsed;
    }

    this.logger?.info('http_request.completed', {
      method,
      path,
      status: response.status,
      duration_ms: Date.now() - startedAt,
    });
    return parsed;
  }

  public async request<T>(
    method: HttpMethodValue,
    path: string,
    body?: unknown,
    options?: HttpRequestOptions,
  ): Promise<Result<T, ApiProblem>> {
    const startedAt = Date.now();
    const url = buildRequestUrl(this.baseUrl, path, options?.params);
    const headers = buildRequestHeaders(method, body !== undefined, this.getToken?.(), options);
    const timeoutMs = options?.timeoutMs ?? this.defaultTimeoutMs;
    const abortContext = createAbortExecutionContext(options?.signal, timeoutMs);

    try {
      return await this.executeAndClassify<T>(
        method,
        path,
        url,
        headers,
        body,
        abortContext.signal,
        startedAt,
      );
    } catch (caught: unknown) {
      const problem = mapTransportFailure(caught);
      emitProblemTelemetry(this.logger, method, path, problem, Date.now() - startedAt);
      return err(problem);
    } finally {
      abortContext.cleanup();
    }
  }

  public get<T>(path: string, options?: HttpRequestOptions): Promise<Result<T, ApiProblem>> {
    return this.request<T>(HttpMethod.GET, path, undefined, options);
  }

  public post<T>(
    path: string,
    body?: unknown,
    options?: HttpRequestOptions,
  ): Promise<Result<T, ApiProblem>> {
    return this.request<T>(HttpMethod.POST, path, body, options);
  }

  public put<T>(
    path: string,
    body?: unknown,
    options?: HttpRequestOptions,
  ): Promise<Result<T, ApiProblem>> {
    return this.request<T>(HttpMethod.PUT, path, body, options);
  }

  public patch<T>(
    path: string,
    body?: unknown,
    options?: HttpRequestOptions,
  ): Promise<Result<T, ApiProblem>> {
    return this.request<T>(HttpMethod.PATCH, path, body, options);
  }

  public delete<T>(path: string, options?: HttpRequestOptions): Promise<Result<T, ApiProblem>> {
    return this.request<T>(HttpMethod.DELETE, path, undefined, options);
  }
}
