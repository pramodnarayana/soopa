import { IpTraceStitchesPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/traces/$traceId/stitches')({
  component: IpTraceStitchesRoute,
});

function IpTraceStitchesRoute() {
  const { traceId } = Route.useParams();
  return <IpTraceStitchesPage key={traceId} traceId={traceId} />;
}
