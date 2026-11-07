import {
  Alert,
  AlertDescription,
  AlertTitle,
  type ApiProblem,
  Button,
  CopyableIdPill,
} from '@soopa/ui';
import { AlertCircle, RefreshCw } from 'lucide-react';
import React from 'react';

export interface ApiProblemBannerProps {
  readonly problem: ApiProblem | null;
  readonly onRetry?: () => void;
  readonly titlePrefix?: string;
}

function FieldErrorList({
  fieldErrors,
}: {
  readonly fieldErrors: Readonly<Record<string, string>> | undefined;
}) {
  if (!fieldErrors) {
    return null;
  }
  const entries = Object.entries(fieldErrors);
  if (entries.length === 0) {
    return null;
  }
  return (
    <ul className="mt-2 list-inside list-disc space-y-0.5 text-xs">
      {entries.map(([field, msg]) => (
        <li key={field}>
          <span className="font-mono font-semibold">{field}</span>: {msg}
        </li>
      ))}
    </ul>
  );
}

export function ApiProblemBanner({
  problem,
  onRetry,
  titlePrefix = 'Operational Request Failed',
}: ApiProblemBannerProps) {
  if (!problem) {
    return null;
  }

  const codeDisplay = problem.serverCode ?? problem.code;

  return (
    <Alert
      variant="destructive"
      className="rounded-xl border-status-critical-border bg-status-critical-bg text-status-critical-fg"
    >
      <AlertCircle className="h-4 w-4" />
      <AlertTitle className="flex flex-wrap items-center justify-between gap-2 font-semibold">
        <span>
          {titlePrefix} ({codeDisplay})
        </span>
        {onRetry ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onRetry}
            className="h-7 gap-1.5 text-xs"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span>Retry</span>
          </Button>
        ) : null}
      </AlertTitle>
      <AlertDescription className="mt-1 space-y-2">
        <p>{problem.message}</p>
        <FieldErrorList fieldErrors={problem.fieldErrors} />
        <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
          {problem.correlationId ? (
            <CopyableIdPill value={problem.correlationId} prefixLabel="Correlation" />
          ) : null}
          {problem.retryAfterSeconds !== undefined ? (
            <span className="rounded-md border border-status-warning-border bg-status-warning-bg px-2 py-0.5 font-mono text-status-warning-fg">
              Retry-After: {problem.retryAfterSeconds}s
            </span>
          ) : null}
        </div>
      </AlertDescription>
    </Alert>
  );
}
