import { IpTransformationsPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export interface IpTransformationsSearchParams {
  readonly connectionId?: string;
}

export const Route = createFileRoute('/_authenticated/tenant/ip/transformations/')({
  validateSearch: (search: Record<string, unknown>): IpTransformationsSearchParams => ({
    connectionId:
      typeof search.connectionId === 'string' && search.connectionId.length > 0
        ? search.connectionId
        : undefined,
  }),
  component: IpTransformationsRoute,
});

function IpTransformationsRoute() {
  const { connectionId } = Route.useSearch();
  return (
    <IpTransformationsPage key={connectionId ?? 'default'} initialConnectionId={connectionId} />
  );
}
