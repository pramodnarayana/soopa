import { createFileRoute, Link, Outlet, useLocation } from '@tanstack/react-router';
import { ChevronRight, Clock, LayoutDashboard, LogOut, Network, Users } from 'lucide-react';
import { useAuth } from 'react-oidc-context';
import { apiClient } from '@/lib/api-client';

export const Route = createFileRoute('/_authenticated')({
  component: AuthenticatedLayout,
});
const NavItem = ({ icon: Icon, label, to }: { icon: any; label: string; to: string }) => {
  const location = useLocation();
  const active = location.pathname === to || location.pathname.startsWith(`${to}/`);
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

function PlatformSidebar() {
  return (
    <>
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-4 mt-2">
        Platform Control
      </div>
      <NavItem icon={LayoutDashboard} label="Overview" to="/" />

      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 px-4 mt-8">
        System Admin
      </div>
      <NavItem icon={Network} label="Tenants" to="/tenants" />
      <NavItem icon={Users} label="Platform Users" to="/users" />
      <NavItem icon={Clock} label="Scheduler" to="/scheduler" />

      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 px-4 mt-8">
        Global Settings
      </div>
      <NavItem icon={Network} label="EDI Platform" to="/edi/partners" />
    </>
  );
}

function TenantSidebar() {
  return (
    <>
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-4 mt-2">
        Overview
      </div>
      <NavItem icon={LayoutDashboard} label="Dashboard" to="/" />

      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 px-4 mt-8">
        EDI Network
      </div>
      <NavItem icon={Network} label="EDI Headers" to="/edi/headers" />
      <NavItem icon={Network} label="Routes" to="/edi/routes" />
      <NavItem icon={Network} label="Webhooks" to="/edi/webhooks" />

      <div className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 px-4 mt-8">
        Configuration
      </div>
      <NavItem icon={Users} label="Trading Partners" to="/edi/partners" />
      <NavItem icon={Clock} label="Tools" to="/edi/tools" />
    </>
  );
}

function AuthenticatedLayout() {
  const auth = useAuth();

  // Keep apiClient in sync with auth state
  if (auth.user?.access_token) {
    apiClient.setToken(auth.user.access_token);
  } else {
    apiClient.setToken(null);
  }

  if (auth.isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-6">
          <div className="w-12 h-12 rounded-full border-4 border-indigo-100 border-t-indigo-600 animate-spin" />
          <p className="text-slate-500 font-medium animate-pulse tracking-wide">
            Authenticating Securely...
          </p>
        </div>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 gap-4">
        <div className="bg-white p-8 rounded-2xl shadow-sm border border-slate-100 max-w-md w-full text-center">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center shadow-md shadow-indigo-500/20 mx-auto mb-6">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="24"
              height="24"
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
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Soopa Platform</h1>
          <p className="text-slate-500 mb-8 text-sm">
            Central command and control for enterprise tenants.
          </p>
          <button
            onClick={() => void auth.signinRedirect()}
            className="w-full bg-indigo-600 text-white font-semibold py-2.5 px-4 rounded-xl hover:bg-indigo-700 transition-colors shadow-sm"
          >
            Login with Zitadel
          </button>
        </div>
      </div>
    );
  }

  const roles =
    (auth.user?.profile['urn:zitadel:iam:org:project:roles'] as Record<string, unknown>) || {};
  const isPlatformAdmin = 'PlatformAdmin' in roles;

  return (
    <div className="min-h-screen flex bg-slate-50/50 text-slate-900 font-sans selection:bg-indigo-100 selection:text-indigo-900">
      {/* Sidebar - Clean White */}
      <aside className="w-72 border-r border-slate-200/60 bg-white flex flex-col fixed inset-y-0 z-50">
        <div className="h-20 flex items-center px-8 border-b border-slate-100/50">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center shadow-md shadow-indigo-500/20">
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
            <h1 className="text-xl font-bold tracking-tight text-slate-900">
              Soopa <span className="font-medium text-slate-400">Platform</span>
            </h1>
          </div>
        </div>

        <nav className="flex-1 px-4 py-8 flex flex-col gap-1.5 overflow-y-auto">
          {isPlatformAdmin ? <PlatformSidebar /> : <TenantSidebar />}
        </nav>

        <div className="p-4 border-t border-slate-200/60">
          <div className="flex items-center gap-3 p-3 rounded-xl bg-slate-900 border border-slate-800 transition-all hover:border-slate-700 shadow-sm">
            <div className="w-10 h-10 rounded-full bg-indigo-500/10 text-indigo-400 flex items-center justify-center font-bold border border-indigo-500/20">
              {auth.user?.profile.email?.charAt(0).toUpperCase() || 'P'}
            </div>
            <div className="flex-1 overflow-hidden">
              <p className="text-sm font-medium text-white truncate">{auth.user?.profile.email}</p>
              <p className="text-xs text-slate-400 truncate">
                {isPlatformAdmin ? 'Platform Admin' : 'Tenant Admin'}
              </p>
            </div>
            <button
              onClick={() => void auth.signoutRedirect()}
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
          <Outlet />
        </div>
      </main>
    </div>
  );
}
