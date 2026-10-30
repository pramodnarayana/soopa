import type { ApiProblem, FrontendLoggerPort, LogAttributes, Result } from '@soopa/ui';

export function logResultOutcome<T>(
  logger: FrontendLoggerPort,
  eventPrefix: string,
  result: Result<T, ApiProblem>,
  attributes?: LogAttributes,
): void {
  if (result.ok) {
    logger.info(`${eventPrefix}.completed`, attributes);
    return;
  }
  logger.error(`${eventPrefix}.failed`, {
    ...attributes,
    error_code: result.error.code,
    status: result.error.status,
    server_code: result.error.serverCode,
    correlation_id: result.error.correlationId,
  });
}
