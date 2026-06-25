import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'

interface TenantProvisioningCardProps {
  isLoading: boolean;
  error: Error | null;
  userProfile?: {
    status: string;
    tenant_id: number;
    rls_enforced_tenant: string | null;
  };
}

export function TenantProvisioningCard({ isLoading, error, userProfile }: TenantProvisioningCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>JIT Tenant Provisioning</CardTitle>
        <CardDescription>Backend isolation verification</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && <p className="text-sm text-slate-500">Fetching isolated tenant profile...</p>}
        {error && <p className="text-sm text-red-500">Error fetching tenant: {error.message}</p>}
        {userProfile && (
          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-sm font-medium text-slate-500">API Status</dt>
              <dd className="mt-1 text-sm text-slate-900">{userProfile.status}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-slate-500">Resolved Tenant ID</dt>
              <dd className="mt-1 text-sm text-slate-900">{userProfile.tenant_id}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-sm font-medium text-slate-500">PostgreSQL RLS Variable (app.current_tenant)</dt>
              <dd className="mt-1 text-sm font-bold text-slate-900">
                {userProfile.rls_enforced_tenant || 'NOT SET (Bypass or Global Admin)'}
              </dd>
            </div>
          </dl>
        )}
      </CardContent>
    </Card>
  )
}
