import { IpConnectionDetailPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/connections/$connectionId')({
  component: IpConnectionDetailRoute,
});

function IpConnectionDetailRoute() {
  const { connectionId } = Route.useParams();
  return <IpConnectionDetailPage key={connectionId} connectionId={connectionId} />;
}
