import { ApiTokensPage } from '@soopa/ui';
import { useAuth } from 'react-oidc-context';
import { UCP_API_URL } from '../../config/ucp';
import { useTenantId } from '../../contexts/TenantContext';

export function DevelopersPage() {
  const auth = useAuth();
  const tenantId = useTenantId();
  const token = auth.user?.access_token ?? '';

  return (
    <div className="p-8">
      <ApiTokensPage baseUrl={UCP_API_URL} tenantId={tenantId} token={token} />
    </div>
  );
}
