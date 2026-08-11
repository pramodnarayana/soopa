import { NotificationsPage } from '@soopa/ui';
import { createFileRoute } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { useTenantContext } from '../../../../contexts/TenantContext';

export const Route = createFileRoute('/_authenticated/tenant/notifications/')({
  component: NotificationsRoute,
});

function NotificationsRoute() {
  const auth = useAuth();
  const { tenantId } = useTenantContext();

  if (!auth.user?.access_token || !tenantId || !auth.user?.profile?.sub) {
    return null;
  }

  return (
    <NotificationsPage
      tenantId={tenantId}
      userId={auth.user.profile.sub}
      accessToken={auth.user.access_token}
    />
  );
}
