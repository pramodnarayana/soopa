import { NotificationsPage } from '@soopa/ui';
import { createFileRoute } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { useTenantContext } from '../../../../contexts/TenantContext';

export const Route = createFileRoute('/_authenticated/tenant/notifications/')({
  component: NotificationsRoute,
});

function NotificationsRoute() {
  const auth = useAuth();
  const { tenantId, token } = useTenantContext();

  if (!token || !tenantId || !auth.user?.profile?.sub) {
    return null;
  }

  return (
    <NotificationsPage
      tenantId={tenantId}
      userId={auth.user.profile.sub}
      accessToken={token}
      apiUrl={
        `${import.meta.env.VITE_UCP_API_URL || 'http://localhost:8000'}`.replace(/\/+$/, '') +
        '/api/v1/notifications'
      }
    />
  );
}
