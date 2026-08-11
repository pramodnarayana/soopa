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

  return <NotificationTemplatesPage tenantId={tenantId} accessToken={token} />;
}
