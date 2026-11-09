import { IpIntervalStreamsPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export interface IpIntervalsSearchParams {
  readonly connectionId?: string;
}

export const Route = createFileRoute('/_authenticated/tenant/ip/intervals/')({
  validateSearch: (search: Record<string, unknown>): IpIntervalsSearchParams => ({
    connectionId:
      typeof search.connectionId === 'string' && search.connectionId.length > 0
        ? search.connectionId
        : undefined,
  }),
  component: IpIntervalsRoute,
});

function IpIntervalsRoute() {
  const { connectionId } = Route.useSearch();
  return (
    <IpIntervalStreamsPage key={connectionId ?? 'default'} initialConnectionId={connectionId} />
  );
}
