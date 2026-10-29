import { ApiErrorCode, type ApiProblem } from '@soopa/ui';
import type { ConnectionCheckResult } from '../../domain/connection';

export function buildFailedCheckProblem(result: ConnectionCheckResult): ApiProblem {
  return {
    code: ApiErrorCode.VALIDATION_ERROR,
    status: 400,
    serverCode: result.errorCode ?? 'CHECK_FAILED',
    message: result.message ?? 'Connector pre-flight check failed.',
  };
}

export function isConnectionSnapshotVerified(
  currentSnapshot: string,
  verifiedSnapshot: string | null,
  checkResult: ConnectionCheckResult | null,
): boolean {
  return verifiedSnapshot === currentSnapshot && checkResult?.success === true;
}
