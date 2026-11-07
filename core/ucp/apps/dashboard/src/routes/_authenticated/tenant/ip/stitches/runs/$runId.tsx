import { IpStitchRunPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/stitches/runs/$runId')({
  component: IpStitchRunRoute,
});

function IpStitchRunRoute() {
  const { runId } = Route.useParams();
  return <IpStitchRunPage key={runId} runId={runId} />;
}
