import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { useAuth } from 'react-oidc-context'

export function IdentityDetailsCard() {
  const auth = useAuth()
  
  return (
    <Card>
      <CardHeader>
        <CardTitle>Identity Details</CardTitle>
        <CardDescription>Pulled directly from Authentik SSO</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-sm font-medium text-slate-500">Email</dt>
            <dd className="mt-1 text-sm text-slate-900">{auth.user?.profile.email}</dd>
          </div>
          <div>
            <dt className="text-sm font-medium text-slate-500">Name</dt>
            <dd className="mt-1 text-sm text-slate-900">{auth.user?.profile.name || 'N/A'}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  )
}
