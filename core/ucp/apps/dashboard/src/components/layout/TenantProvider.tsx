import { NotificationBell } from '@soopa/ui';
import { LogOut } from 'lucide-react';
import type { ReactNode } from 'react';
import { useAuth } from 'react-oidc-context';
import { TenantContext } from '../../contexts/TenantContext';
import { useGetTenant } from '../../domains/tenants/api/queries';
import { resolveTenantId } from '../../lib/auth';

const logger = console;

export interface TenantProviderProps {
  children: (props: {
    sidebarHeader: ReactNode;
    userProfile: ReactNode;
    headerContent: ReactNode;
    tenantSubscriptions: string[];
  }) => ReactNode;
}

export function TenantProvider({ children }: TenantProviderProps) {
  const auth = useAuth();
  const token = auth.user?.access_token ?? '';
  const tenantId = resolveTenantId(token, auth.user?.profile ?? {});

  const { data: tenant } = useGetTenant(tenantId ?? '');

  if (auth.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50/50">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  if (!auth.isLoading && !tenantId) {
    // Log diagnostic details without exposing PII in the error message
    logger.error('Tenant ID resolution failed', {
      hasToken: !!token,
      hasUser: !!auth.user,
      profileKeyCount: Object.keys(auth.user?.profile ?? {}).length,
    });

    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50/50">
        <div className="max-w-md p-8 bg-white rounded-lg shadow-md border border-slate-200">
          <h1 className="text-xl font-bold text-slate-900 mb-4">Configuration Error</h1>
          <p className="text-slate-600 mb-4">
            Your account is not properly configured. Please contact your administrator.
          </p>
          <button
            onClick={() => void auth.signoutRedirect()}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Sign Out
          </button>
        </div>
      </div>
    );
  }

  const sidebarHeader = (
    <div className="flex items-center gap-4 w-full">
      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center shadow-md shadow-indigo-500/20 shrink-0">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="white"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1-1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
        </svg>
      </div>
      <h1 className="text-xl font-bold tracking-tight text-foreground truncate">
        {tenant ? tenant.name : 'Loading...'}
      </h1>
    </div>
  );

  const userProfile = (
    <div className="flex items-center gap-4 p-4 rounded-xl hover:bg-accent transition-colors group">
      <div className="w-12 h-12 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-lg">
        {auth.user?.profile.email?.charAt(0).toUpperCase() || 'T'}
      </div>
      <div className="flex-1 overflow-hidden">
        <p className="text-base font-semibold text-foreground truncate">
          {auth.user?.profile.email}
        </p>
        <p className="text-xs text-muted-foreground truncate uppercase tracking-widest mt-1">
          Tenant Admin
        </p>
      </div>
      <button
        onClick={() => void auth.signoutRedirect()}
        aria-label="Sign out"
        className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors opacity-0 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2"
      >
        <LogOut className="w-5 h-5" />
      </button>
    </div>
  );

  const finalTenantId = tenant?.id ?? tenantId ?? '';

  const headerContent = (
    <NotificationBell
      tenantId={finalTenantId}
      userId={auth.user?.profile?.sub ?? ''}
      accessToken={token}
    />
  );

  return (
    <TenantContext.Provider value={{ tenantId: finalTenantId, token }}>
      {children({
        sidebarHeader,
        userProfile,
        headerContent,
        tenantSubscriptions: tenant?.subscriptions ?? [],
      })}
    </TenantContext.Provider>
  );
}
