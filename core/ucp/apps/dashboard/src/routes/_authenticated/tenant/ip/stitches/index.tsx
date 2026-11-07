import { IpStitchesPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/stitches/')({
  component: IpStitchesRoute,
});

function IpStitchesRoute() {
  return <IpStitchesPage />;
}
