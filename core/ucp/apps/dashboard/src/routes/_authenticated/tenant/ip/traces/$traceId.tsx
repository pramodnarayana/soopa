import { IpTraceWaterfallPage } from '@soopa/ip-ui';
import { createFileRoute, Outlet, useChildMatches } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/tenant/ip/traces/$traceId')({
  component: IpTraceRoute,
});

function IpTraceRoute() {
  const { traceId } = Route.useParams();
  const childMatches = useChildMatches();

  if (childMatches.length > 0) {
    return <Outlet />;
  }

  return <IpTraceWaterfallPage key={traceId} traceId={traceId} />;
}
