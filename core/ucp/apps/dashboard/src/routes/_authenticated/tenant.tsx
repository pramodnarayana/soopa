import { createFileRoute, Link, Outlet, useLocation } from '@tanstack/react-router';
import type { LucideIcon } from 'lucide-react';
import {
  ArrowLeftRight,
  ChevronRight,
  LayoutDashboard,
  LogOut,
  Network,
  Settings,
} from 'lucide-react';
import { useAuth } from 'react-oidc-context';
import { TenantContext } from '../../contexts/TenantContext';
import { useGetTenant } from '../../domains/tenants/api/queries';
import { resolveTenantId } from '../../lib/auth';

export const Route = createFileRoute('/_authenticated/tenant')({
  component: TenantLayout,
});

const NavItem = ({
  icon: Icon,
  label,
  to,
  exact,
}: {
  icon: LucideIcon;
  label: string;
  to: string;
  exact?: boolean;
}) => {
  const location = useLocation();
  const active = exact
    ? location.pathname === to
    : location.pathname === to || location.pathname.startsWith(`${to}/`);
  return (
    <Link
      to={to}
      className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group ${active ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-sm' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'}`}
    >
      <Icon
        className={`w-5 h-5 ${active ? 'text-indigo-600' : 'text-slate-400 group-hover:text-slate-600 transition-colors'}`}
      />
      <span>{label}</span>
      {active && <ChevronRight className="w-4 h-4 ml-auto text-indigo-400" />}
    </Link>
  );
};

function TenantSidebar({ subscriptions }: { subscriptions: string[] }) {
  const isEdiSubscribed = subscriptions.includes('edi');

  return (
    <>
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-4 mt-2">
        Overview
      </div>
      <NavItem icon={LayoutDashboard} label="Dashboard" to="/tenant" exact />

      {isEdiSubscribed && (
        <>
          <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 px-4 mt-8">
            EDI
          </div>
          <NavItem icon={LayoutDashboard} label="EDI Dashboard" to="/tenant/edi" exact />
          <NavItem icon={ArrowLeftRight} label="Transactions" to="/tenant/edi/transactions" />
          <NavItem icon={Network} label="EDI Headers" to="/tenant/edi/headers" />
          <NavItem icon={Network} label="Routes" to="/tenant/edi/routes" />
        </>
      )}

      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 px-4 mt-8">
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
    <div className="min-h-screen flex bg-slate-50/50 text-slate-900 font-sans selection:bg-indigo-100 selection:text-indigo-900">
      {/* Sidebar - Clean White */}
      <aside className="w-72 border-r border-slate-200/60 bg-white flex flex-col fixed inset-y-0 z-50">
        <div className="h-20 flex items-center px-8 border-b border-slate-100/50">
          <div className="flex items-center gap-3 w-full">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center shadow-md shadow-indigo-500/20 shrink-0">
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
            <h1 className="text-xl font-bold tracking-tight text-slate-900 truncate">
              {tenant ? tenant.name : 'Loading...'}
            </h1>
          </div>
        </div>

        <nav className="flex-1 px-4 py-8 flex flex-col gap-1.5 overflow-y-auto">
          <TenantSidebar subscriptions={tenant?.subscriptions ?? []} />
        </nav>

        <div className="p-4 border-t border-slate-200/60">
          <div className="flex items-center gap-3 p-3 rounded-xl bg-slate-900 border border-slate-800 transition-all hover:border-slate-700 shadow-sm">
            <div className="w-10 h-10 rounded-full bg-indigo-500/10 text-indigo-400 flex items-center justify-center font-bold border border-indigo-500/20">
              {auth.user?.profile.email?.charAt(0).toUpperCase() || 'T'}
            </div>
            <div className="flex-1 overflow-hidden">
              <p className="text-sm font-medium text-white truncate">{auth.user?.profile.email}</p>
              <p className="text-xs text-slate-400 truncate">Tenant Admin</p>
            </div>
            <button
              onClick={() => void auth.signoutRedirect()}
              aria-label="Sign out"
              className="p-2 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 ml-72 bg-slate-50">
        <div className="max-w-[1400px] mx-auto p-8 lg:p-12">
          <TenantContext.Provider value={{ tenantId: tenant?.id ?? tenantId, token }}>
            <Outlet />
          </TenantContext.Provider>
        </div>
      </main>
    </div>
  );
}
