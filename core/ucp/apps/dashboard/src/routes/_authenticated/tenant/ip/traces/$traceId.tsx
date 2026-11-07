import { IpTraceWaterfallPage } from '@soopa/ip-ui';
import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/traces/$traceId')({
  component: IpTraceWaterfallRoute,
});

function IpTraceWaterfallRoute() {
  const { traceId } = Route.useParams();
  return <IpTraceWaterfallPage key={traceId} traceId={traceId} />;
}
