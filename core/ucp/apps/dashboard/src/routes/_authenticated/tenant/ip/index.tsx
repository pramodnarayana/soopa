import { IpCommandCenterPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/')({
  component: IpCommandCenterRoute,
});

function IpCommandCenterRoute() {
  return <IpCommandCenterPage />;
}
