import { IpStitchDefinitionPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

interface StitchDefinitionSearch {
  readonly traceId?: string;
  readonly runId?: string;
  readonly tab?: 'canvas' | 'executions' | 'data';
}

export const Route = createFileRoute('/_authenticated/tenant/ip/stitches/definitions/$workflowId')({
  validateSearch: (search: Record<string, unknown>): StitchDefinitionSearch => ({
    traceId: typeof search.traceId === 'string' ? search.traceId : undefined,
    runId: typeof search.runId === 'string' ? search.runId : undefined,
    tab:
      search.tab === 'canvas' || search.tab === 'executions' || search.tab === 'data'
        ? search.tab
        : undefined,
  }),
  component: IpStitchDefinitionRoute,
});

function IpStitchDefinitionRoute() {
  const { workflowId } = Route.useParams();
  const search = Route.useSearch();
  return (
    <IpStitchDefinitionPage
      key={workflowId}
      workflowId={workflowId}
      initialTraceId={search.traceId}
      initialRunId={search.runId}
      initialTab={search.tab}
    />
  );
}
