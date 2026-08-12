import { NotificationTemplatesPage } from '@soopa/ui';
import { createFileRoute } from '@tanstack/react-router';
import { useTenantContext } from '../../../../contexts/TenantContext';

export const Route = createFileRoute('/_authenticated/tenant_/settings/notifications/templates')({
  component: NotificationTemplatesRoute,
});

function NotificationTemplatesRoute() {
  const { tenantId, token } = useTenantContext();

  if (!tenantId) {
    return null;
  }

  const apiUrl =
    `${import.meta.env.VITE_UCP_API_URL || 'http://localhost:8000'}`.replace(/\/+$/, '') +
    '/api/v1/notifications';
  return <NotificationTemplatesPage tenantId={tenantId} accessToken={token} apiUrl={apiUrl} />;
}
