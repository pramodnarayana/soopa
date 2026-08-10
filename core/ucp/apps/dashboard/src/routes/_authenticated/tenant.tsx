import { createFileRoute, Outlet } from '@tanstack/react-router';
import { ArrowLeftRight, LayoutDashboard, LogOut, Network, Settings } from 'lucide-react';
import { useAuth } from 'react-oidc-context';
import { AppLayout } from '../../components/layout/AppLayout';
import { NavItem } from '../../components/layout/NavItem';
import { TenantContext } from '../../contexts/TenantContext';
import { useGetTenant } from '../../domains/tenants/api/queries';
import { resolveTenantId } from '../../lib/auth';

export const Route = createFileRoute('/_authenticated/tenant')({
  component: TenantLayout,
});

function TenantSidebar({ subscriptions }: { subscriptions: string[] }) {
  const isEdiSubscribed = subscriptions.includes('edi');

  return (
    <>
      <div className="text-[18px] font-bold text-muted-foreground uppercase tracking-widest mb-3 px-4 mt-2">
        Overview
      </div>
      <NavItem icon={LayoutDashboard} label="Dashboard" to="/tenant" exact />

      {isEdiSubscribed && (
        <>
          <div className="text-[18px] font-bold text-muted-foreground uppercase tracking-widest mb-3 px-4 mt-8">
            EDI
          </div>
          <NavItem icon={LayoutDashboard} label="EDI Dashboard" to="/tenant/edi" exact />
          <NavItem icon={ArrowLeftRight} label="Transactions" to="/tenant/edi/transactions" />
          <NavItem icon={Settings} label="EDI Setup" to="/tenant/edi/setup" />
        </>
      )}

      <div className="text-[18px] font-bold text-muted-foreground uppercase tracking-widest mb-3 px-4 mt-8">
        Developer Settings
      </div>
      <NavItem icon={Network} label="Webhooks" to="/tenant/developer/webhooks" />
      <NavItem icon={Settings} label="API Tokens" to="/tenant/developer/api-tokens" />
      <NavItem icon={Settings} label="EDI Tool" to="/tenant/edi/tool" />
    </>
  );
}

function TenantLayout() {
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

  if (!tenantId) {
    throw new Error(
      'FATAL: Tenant ID is missing from both the access token and user profile. ' +
        'This user may not be assigned to a Zitadel organization. ' +
        `Access token present: ${!!token}, Profile keys: ${Object.keys(auth.user?.profile ?? {}).join(', ')}`,
    );
  }

  return (
    <TenantContext.Provider value={{ tenantId: tenant?.id ?? tenantId, token }}>
      <AppLayout
        sidebarHeader={
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
                <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
              </svg>
            </div>
            <h1 className="text-xl font-bold tracking-tight text-foreground truncate">
              {tenant ? tenant.name : 'Loading...'}
            </h1>
          </div>
        }
        sidebarNavigation={<TenantSidebar subscriptions={tenant?.subscriptions ?? []} />}
        userProfile={
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
              className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
            >
              <LogOut className="w-5 h-5" />
            </button>
          </div>
        }
      >
        <Outlet />
      </AppLayout>
    </TenantContext.Provider>
  );
}
