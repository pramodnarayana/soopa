import { NotificationsPage } from '@soopa/ui';
import { createFileRoute } from '@tanstack/react-router';
import { useTenantContext } from '../../../../contexts/TenantContext';
import { useAuthUser } from '../../../../hooks/useAuthUser';

export const Route = createFileRoute('/_authenticated/tenant/notifications/')({
  component: NotificationsRoute,
});

function NotificationsRoute() {
  const { tenantId, token } = useTenantContext();
  // Use canonical platform user ID (usr_...) from /auth/me, NOT the raw Zitadel IDP sub.
  // This enforces the architectural rule: all internal operations use platform-canonical IDs.
  const { data: authUser } = useAuthUser();
  const canonicalUserId = authUser?.subject ?? '';

  if (!token || !tenantId || !canonicalUserId) {
    return null;
  }

  return (
    <NotificationsPage
      tenantId={tenantId}
      userId={canonicalUserId}
      accessToken={token}
      apiUrl={
        `${import.meta.env.VITE_UCP_API_URL || 'http://localhost:8000'}`.replace(/\/+$/, '') +
        '/api/v1/notifications'
      }
    />
  );
}
