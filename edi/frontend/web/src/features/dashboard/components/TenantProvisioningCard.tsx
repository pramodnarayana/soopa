import { Database, Shield, Lock, AlertCircle, RefreshCcw } from 'lucide-react'

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
    <div className="group relative flex flex-col gap-4 rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm transition-all duration-200 hover:shadow-md hover:border-orange-500/30 hover:-translate-y-0.5">

      <div className="flex items-start justify-between">
         <div className="flex items-center gap-4">
           <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white border border-slate-200 shadow-sm overflow-hidden text-orange-600 transition-colors group-hover:bg-orange-50/50">
            <Database className="h-7 w-7" />
          </div>
          <div className="flex flex-col">
            <h3 className="text-lg font-bold tracking-tight text-slate-900">Tenant Provisioning</h3>
            <div className="flex items-center gap-1.5 mt-0.5 text-sm text-slate-500 font-medium">
              <Shield className="h-4 w-4 text-orange-500" /> Data plane isolation
            </div>
          </div>
         </div>

         {isLoading && <RefreshCcw className="h-5 w-5 text-slate-400 animate-spin" />}
      </div>

      <div className="mt-2 flex-1 flex flex-col justify-end border-t border-slate-100 pt-4">
        {isLoading && (
           <div className="flex flex-col items-center justify-center py-6 gap-3">
             <div className="w-8 h-8 rounded-full border-2 border-slate-200 border-t-orange-500 animate-spin" />
             <p className="text-sm font-medium text-slate-400">Verifying JIT tenant context...</p>
           </div>
        )}

        {error && (
          <div className="rounded-xl bg-red-50 p-4 border border-red-100 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
            <div className="text-sm text-red-700 font-medium">
              Failed to fetch isolated tenant profile.
              <span className="block font-normal mt-1 opacity-80">{error.message}</span>
            </div>
          </div>
        )}

        {userProfile && (
           <div className="grid grid-cols-2 gap-x-4 gap-y-4">
             <div className="col-span-1 rounded-xl p-3 bg-slate-50 border border-slate-100">
               <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">API Status</p>
               <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-emerald-500" />
                  <p className="text-sm font-bold text-slate-800">{userProfile.status}</p>
               </div>
             </div>

             <div className="col-span-1 rounded-xl p-3 bg-slate-50 border border-slate-100">
               <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Resolved Tenant ID</p>
               <div className="flex items-center gap-1.5 text-indigo-600">
                  <Lock className="w-3.5 h-3.5" />
                  <p className="text-sm font-bold">{userProfile.tenant_id}</p>
               </div>
             </div>

             <div className="col-span-2 rounded-xl p-3 bg-slate-50 border border-slate-200">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">PostgreSQL RLS Variable</p>
                  <Shield className="w-3.5 h-3.5 text-emerald-500" />
                </div>
                <div className="font-mono text-sm break-all">
                  <span className="text-indigo-600">app.current_tenant</span>
                  <span className="text-slate-500 mx-2">=</span>
                  <span className="text-emerald-600 font-bold">{userProfile.rls_enforced_tenant || 'NULL (Global)'}</span>
                </div>
             </div>
           </div>
        )}
      </div>
    </div>
  )
}
