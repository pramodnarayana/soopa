import { type IpNavigationPort, IpUIProvider } from '@soopa/ip-ui';
import { AppNotSubscribed } from '@soopa/ui';
import { createFileRoute, Outlet, useNavigate } from '@tanstack/react-router';
import { Loader2 } from 'lucide-react';
import { useMemo } from 'react';
import { useTenantContext } from '../../../contexts/TenantContext';
import { useGetTenant } from '../../../domains/tenants/api/queries';
import { config } from '../../../lib/config';

export const Route = createFileRoute('/_authenticated/tenant/ip')({
  component: IpLayout,
});

function IpLayout() {
  const { tenantId, token } = useTenantContext();
  const navigate = useNavigate();
  const { data: tenant, isLoading, isError, error, refetch } = useGetTenant(tenantId);

  const navigation = useMemo<IpNavigationPort>(
    () => ({
      toCommandCenter: () => {
        void navigate({ to: '/tenant/ip' });
      },
      toTraces: (correlationQuery?: string) => {
        void navigate({
          to: '/tenant/ip/traces',
          search: correlationQuery ? { q: correlationQuery } : {},
        });
      },
      toTraceDetail: (traceId: string) => {
        void navigate({
          to: '/tenant/ip/traces/$traceId',
          params: { traceId },
        });
      },
      toConnections: () => {
        void navigate({ to: '/tenant/ip/connections' });
      },
      toConnectionDetail: (connectionId: string) => {
        void navigate({
          to: '/tenant/ip/connections/$connectionId',
          params: { connectionId },
        });
      },
      toTransformations: (connectionId?: string) => {
        void navigate({
          to: '/tenant/ip/transformations',
          search: connectionId ? { connectionId } : {},
        });
      },
      toStitches: () => {
        void navigate({ to: '/tenant/ip/stitches' });
      },
      toStitchDefinition: (workflowId: string) => {
        void navigate({
          to: '/tenant/ip/stitches/definitions/$workflowId',
          params: { workflowId },
        });
      },
      toStitchRun: (runId: string) => {
        void navigate({
          to: '/tenant/ip/stitches/runs/$runId',
          params: { runId },
        });
      },
    }),
    [navigate],
  );

  if (isLoading) {
    return (
      <div className="flex min-h-full flex-1 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 text-center">
        <p className="text-sm font-medium text-red-600">
          Failed to load tenant subscription status:{' '}
          {error instanceof Error ? error.message : 'Unknown error'}
        </p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="inline-flex items-center justify-center rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          Retry
        </button>
      </div>
    );
  }

  const isIpSubscribed = Boolean(tenant?.subscriptions?.includes('ip'));
  if (!isIpSubscribed) {
    return <AppNotSubscribed appName="Integration Platform" />;
  }

  return (
    <IpUIProvider
      baseUrl={config.apiOrigin}
      tenantId={tenantId}
      token={token}
      navigation={navigation}
    >
      <Outlet />
    </IpUIProvider>
  );
}
