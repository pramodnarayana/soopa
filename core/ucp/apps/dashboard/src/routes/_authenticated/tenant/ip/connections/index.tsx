import { IpConnectionsPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/connections/')({
  component: IpConnectionsRoute,
});

function IpConnectionsRoute() {
  return <IpConnectionsPage />;
}
