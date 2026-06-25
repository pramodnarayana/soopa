import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'

interface TenantProvisioningCardProps {
  isLoading: boolean;
  error: Error | null;
  userProfile?: {
    user: { id: number };
    tenant: { id: number; name: string; shard_id: number };
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
              <dt className="text-sm font-medium text-slate-500">Internal User ID</dt>
              <dd className="mt-1 text-sm text-slate-900">{userProfile.user.id}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-slate-500">Internal Tenant ID</dt>
              <dd className="mt-1 text-sm text-slate-900">{userProfile.tenant.id}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-slate-500">Tenant Name</dt>
              <dd className="mt-1 text-sm font-bold text-slate-900">{userProfile.tenant.name}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-slate-500">Database Shard</dt>
              <dd className="mt-1 text-sm text-slate-900">{userProfile.tenant.shard_id}</dd>
            </div>
          </dl>
        )}
      </CardContent>
    </Card>
  )
}
