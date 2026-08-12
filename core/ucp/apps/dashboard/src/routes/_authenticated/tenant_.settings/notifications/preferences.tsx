import { NotificationPreferencesPage } from '@soopa/ui';
import { createFileRoute } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { useTenantContext } from '../../../../contexts/TenantContext';

export const Route = createFileRoute('/_authenticated/tenant_/settings/notifications/preferences')({
  component: NotificationPreferencesRoute,
});

function NotificationPreferencesRoute() {
  const auth = useAuth();
  const { tenantId, token } = useTenantContext();

  if (!auth.user?.access_token || !tenantId) {
    return null;
  }

  const apiUrl =
    `${import.meta.env.VITE_UCP_API_URL || 'http://localhost:8000'}`.replace(/\/+$/, '') +
    '/api/v1/notifications';
  return <NotificationPreferencesPage tenantId={tenantId} accessToken={token} apiUrl={apiUrl} />;
}
