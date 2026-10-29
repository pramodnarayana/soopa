import type { FrontendLoggerPort, LogAttributes } from '../observability';
import type { ApiProblem, Result } from './ports';

export interface PlatformResultQuerySource<T> {
  readonly data: Result<T, ApiProblem> | undefined;
  readonly isLoading: boolean;
  readonly isFetching: boolean;
  readonly isError: boolean;
  readonly refetch: () => Promise<unknown>;
}

export interface PlatformResultQueryView<T> {
  readonly data: T | undefined;
  readonly problem: ApiProblem | null;
  readonly error: ApiProblem | null;
  readonly isError: boolean;
  readonly isLoading: boolean;
  readonly isFetching: boolean;
  readonly refetch: () => Promise<unknown>;
}

/**
 * Projects a TanStack Query wrapping Result<T, ApiProblem> into a UI-friendly view
 * without throwing exceptions inside queryFn for expected HTTP/network errors.
 */
export function projectPlatformResultQuery<T>(
  query: PlatformResultQuerySource<T>,
): PlatformResultQueryView<T> {
  const result = query.data;
  const problem = result && !result.ok ? result.error : null;
  return {
    data: result?.ok ? result.value : undefined,
    problem,
    error: problem,
    isError: query.isError || problem !== null,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    refetch: query.refetch,
  };
}

/**
 * Emits structured INFO/ERROR telemetry for a Result-returning platform mutation
 * and returns true iff the mutation succeeded (so callers can gate cache invalidation).
 */
export function recordPlatformMutationOutcome<T>(
  logger: FrontendLoggerPort,
  eventPrefix: string,
  result: Result<T, ApiProblem>,
  attributes?: LogAttributes,
): boolean {
  if (result.ok) {
    logger.info(`${eventPrefix}.succeeded`, attributes);
    return true;
  }
  logger.error(`${eventPrefix}.failed`, {
    ...attributes,
    error_code: result.error.code,
    status: result.error.status,
    detail: result.error.message,
    correlation_id: result.error.correlationId,
  });
  return false;
}
