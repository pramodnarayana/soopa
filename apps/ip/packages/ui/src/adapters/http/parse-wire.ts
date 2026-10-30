import {
  ApiErrorCode,
  type ApiProblem,
  err,
  type FrontendLoggerPort,
  ok,
  type Result,
} from '@soopa/ui';
import type { z } from 'zod';

export function parseAndMapResult<TWire, TDomain>(
  rawResult: Result<unknown, ApiProblem>,
  schema: z.ZodType<TWire>,
  mapper: (wire: TWire) => TDomain,
  context: string,
  logger?: FrontendLoggerPort,
): Result<TDomain, ApiProblem> {
  if (!rawResult.ok) {
    return rawResult;
  }
  const parsed = schema.safeParse(rawResult.value);
  if (!parsed.success) {
    const firstIssue = parsed.error.issues[0];
    const pathLabel =
      firstIssue && firstIssue.path.length > 0 ? firstIssue.path.join('.') : '<root>';
    const issueMessage = firstIssue ? firstIssue.message : 'Invalid wire payload';
    logger?.error('http_wire.schema_drift', {
      context,
      issue_path: pathLabel,
      issue_message: issueMessage,
    });
    return err({
      code: ApiErrorCode.SCHEMA_DRIFT,
      status: 200,
      message: `Wire schema drift in ${context} (${pathLabel}: ${issueMessage})`,
    });
  }
  return ok(mapper(parsed.data));
}
