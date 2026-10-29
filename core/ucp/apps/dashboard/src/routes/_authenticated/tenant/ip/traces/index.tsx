import { IpTracesTimelinePage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export interface IpTracesSearchParams {
  readonly q?: string;
}

export const Route = createFileRoute('/_authenticated/tenant/ip/traces/')({
  validateSearch: (search: Record<string, unknown>): IpTracesSearchParams => ({
    q: typeof search.q === 'string' && search.q.length > 0 ? search.q : undefined,
  }),
  component: IpTracesTimelineRoute,
});

function IpTracesTimelineRoute() {
  const { q } = Route.useSearch();
  return <IpTracesTimelinePage key={q ?? 'all'} initialCorrelationQuery={q} />;
}
