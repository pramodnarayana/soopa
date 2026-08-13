import { Badge } from '@soopa/ui/components/ui/badge';
import { Button } from '@soopa/ui/components/ui/button';
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@soopa/ui/components/ui/card';
import { createFileRoute } from '@tanstack/react-router';
import { Box, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { useSubscribeTenant, useUnsubscribeTenant } from '@/domains/apps/api/mutations';
import { useGetApps, useGetTenantSubscriptions } from '@/domains/apps/api/queries';

export const Route = createFileRoute('/_authenticated/platform/tenants/$tenantId/apps')({
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
          <Card key={app.id}>
            {isSubscribed && (
              <div className="absolute top-4 right-4 flex items-center gap-2">
                <Badge variant="default">
                  <span className="h-1.5 w-1.5 rounded-full bg-white animate-pulse" />
                  Active
                </Badge>
                <CheckCircle2 className="w-6 h-6 text-primary animate-in zoom-in" />
              </div>
            )}

            <CardHeader>
              <div
                className={`w-12 h-12 rounded-xl flex items-center justify-center transition-colors ${
                  isSubscribed
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground'
                }`}
              >
                <Box className="w-6 h-6" />
              </div>

              <div className="space-y-1">
                <CardTitle>{app.name}</CardTitle>
                <CardDescription>
                  {app.description || 'Enterprise integration application'}
                </CardDescription>
              </div>
            </CardHeader>

            <CardFooter>
              {isSubscribed ? (
                <Button
                  variant="destructive"
                  fullWidth={true}
                  disabled={unsubscribeMutationObj.isPending}
                  onClick={() => handleUnsubscribe(app.id)}
                >
                  {unsubscribeMutationObj.isPending ? 'Removing...' : 'Unsubscribe'}
                </Button>
              ) : (
                <Button
                  fullWidth={true}
                  size="cta"
                  disabled={subscribeMutationObj.isPending}
                  onClick={() => handleSubscribe(app.id)}
                >
                  {subscribeMutationObj.isPending ? 'Subscribing...' : 'Subscribe'}
                </Button>
              )}
            </CardFooter>
          </Card>
        );
      })}
    </div>
  );
}
