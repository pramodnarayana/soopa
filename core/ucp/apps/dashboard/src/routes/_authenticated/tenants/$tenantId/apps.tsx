import { createFileRoute } from '@tanstack/react-router';
import { Box, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { useSubscribeTenant, useUnsubscribeTenant } from '@/domains/apps/api/mutations';
import { useGetApps, useGetTenantSubscriptions } from '@/domains/apps/api/queries';

export const Route = createFileRoute('/_authenticated/tenants/$tenantId/apps')({
  component: TenantAppsPage,
});

function TenantAppsPage() {
  const { tenantId } = Route.useParams();

  const { data: apps = [], isLoading: appsLoading } = useGetApps();
  const { data: subscriptions = [], isLoading: subsLoading } = useGetTenantSubscriptions(tenantId);

  const subscribeMutationObj = useSubscribeTenant();
  const unsubscribeMutationObj = useUnsubscribeTenant();

  const handleSubscribe = (appId: string) => {
    subscribeMutationObj.mutate(
      { tenantId, appId },
      {
        onSuccess: () => {
          toast.success('Successfully subscribed to application');
        },
        onError: (err: Error) => {
          toast.error(err.message || 'Failed to subscribe to application');
        },
      },
    );
  };

  const handleUnsubscribe = (appId: string) => {
    unsubscribeMutationObj.mutate(
      { tenantId, appId },
      {
        onSuccess: () => {
          toast.success('Successfully unsubscribed from application');
        },
        onError: (err: Error) => {
          toast.error(err.message || 'Failed to unsubscribe from application');
        },
      },
    );
  };

  if (appsLoading || subsLoading) {
    return <div className="text-slate-500">Loading applications...</div>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      {apps.map((app: { id: string; name: string; description?: string }) => {
        const isSubscribed = subscriptions.some(
          (sub: { appId: string; status: string }) =>
            sub.appId === app.id && sub.status === 'active',
        );

        return (
          <div
            key={app.id}
            className={`relative group flex flex-col overflow-hidden rounded-2xl border p-6 transition-all duration-200 ${
              isSubscribed
                ? 'border-emerald-600 bg-emerald-50/50 shadow-sm'
                : 'border-slate-200 bg-white hover:shadow-md'
            }`}
          >
            {isSubscribed && (
              <div className="absolute top-4 right-4 flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700 border border-emerald-200">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Active
                </span>
                <CheckCircle2 className="w-6 h-6 text-emerald-600 animate-in zoom-in" />
              </div>
            )}

            <div className="flex flex-col gap-4 flex-grow mt-2">
              <div
                className={`w-12 h-12 rounded-xl flex items-center justify-center ${isSubscribed ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-600'} transition-colors`}
              >
                <Box className="w-6 h-6" />
              </div>

              <div className="space-y-1">
                <h3
                  className={`text-lg font-semibold ${isSubscribed ? 'text-emerald-950' : 'text-slate-900'}`}
                >
                  {app.name}
                </h3>
                <p className={`text-sm ${isSubscribed ? 'text-emerald-900/70' : 'text-slate-500'}`}>
                  {app.description || 'Enterprise integration application'}
                </p>
              </div>
            </div>

            <div className="mt-6 pt-4 border-t border-slate-200/60 flex justify-center">
              {isSubscribed ? (
                <Button
                  variant="outline"
                  className="w-full text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
                  disabled={unsubscribeMutationObj.isPending}
                  onClick={() => handleUnsubscribe(app.id)}
                >
                  {unsubscribeMutationObj.isPending ? 'Removing...' : 'Unsubscribe'}
                </Button>
              ) : (
                <Button
                  className="w-full bg-indigo-600 hover:bg-indigo-700 text-white"
                  disabled={subscribeMutationObj.isPending}
                  onClick={() => handleSubscribe(app.id)}
                >
                  {subscribeMutationObj.isPending ? 'Subscribing...' : 'Subscribe'}
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
