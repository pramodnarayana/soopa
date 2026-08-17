import { NotificationBell } from '@soopa/ui';
import { Button } from '@soopa/ui/components/ui/button';
import { createRoute, Link, Outlet, useLocation } from '@tanstack/react-router';
import {
  ChevronDown,
  ChevronRight,
  Database,
  LogOut,
  Network,
  Settings,
  Terminal,
  Users,
  Wrench,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useAuth } from 'react-oidc-context';
import { useDashboardData } from '../features/dashboard/api/useDashboardData';
import { SFTPPartnersProvider } from '../features/partners/context/SFTPPartnersContext';
import { useAuthMe } from '../hooks/useAuthMe';
import { Route as rootRoute } from './__root';

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  id: 'app',
  component: AppWrapper,
});

export function AppWrapper() {
  return (
    <SFTPPartnersProvider>
      <AppLayout />
    </SFTPPartnersProvider>
  );
}

const NavItem = ({
  icon: Icon,
  label,
  to,
  indent = false,
}: {
  icon: any;
  label: string;
  to: string;
  indent?: boolean;
}) => {
  const location = useLocation();
  const active = location.pathname.startsWith(to);
  return (
    <Link
      to={to}
      className={`flex items-center gap-3 py-3 rounded-xl transition-all duration-200 group ${indent ? 'pl-11 pr-4' : 'px-4'} ${active ? 'bg-indigo-50 text-indigo-700 font-semibold shadow-sm' : 'text-slate-500 font-medium hover:bg-slate-50 hover:text-slate-900'}`}
    >
      <Icon
        className={`w-5 h-5 ${active ? 'text-indigo-600' : 'text-slate-400 group-hover:text-slate-600 transition-colors'}`}
      />
      <span>{label}</span>
      {active && <ChevronRight className="w-4 h-4 ml-auto text-indigo-400" />}
    </Link>
  );
};

const NavGroup = ({
  icon: Icon,
  label,
  children,
  defaultExpanded = true,
}: {
  icon: any;
  label: string;
  children: React.ReactNode;
  defaultExpanded?: boolean;
}) => {
  const [expanded, setExpanded] = useState(defaultExpanded);
  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium w-full text-left"
      >
        <Icon className="w-5 h-5 text-slate-400 group-hover:text-slate-600 transition-colors" />
        <span className="flex-1">{label}</span>
        <ChevronDown
          className={`w-4 h-4 text-slate-400 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
        />
      </button>
      {expanded && <div className="flex flex-col gap-1">{children}</div>}
    </div>
  );
};

import { useTenantId } from '../contexts/TenantContext';

export function AppLayout() {
  const auth = useAuth();
  const tenantId = useTenantId();
  const redirectTriggered = useRef(false);
  // 1. Fetch user data (role, features)
  const { data: userProfile, isLoading: isProfileLoading } = useDashboardData();
  // Use canonical platform user ID (usr_...) from /auth/me, NOT the raw Zitadel IDP sub.
  // This enforces the architectural rule: all internal operations use platform-canonical IDs.
  const { data: authMe } = useAuthMe();
  const canonicalUserId = authMe?.subject ?? '';

  // 2. Strict Authentication Guard
  useEffect(() => {
    if (!auth.isAuthenticated && !auth.isLoading && !redirectTriggered.current) {
      redirectTriggered.current = true;
      void auth.signinRedirect();
    }
  }, [auth.isAuthenticated, auth.isLoading, auth]);

  if (!auth.isAuthenticated && !auth.isLoading) {
    return null;
  }

  if (auth.isLoading || isProfileLoading) {
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

  // 3. Strict RBAC Guard (If Platform Admin, redirect to platform)
  if (userProfile?.is_platform_admin) {
    // Basic redirect for prototype. In production, use TanStack navigate.
    window.location.href = '/platform/dashboard';
    return null;
  }

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
              Soopa <span className="font-medium text-slate-400">EDI</span>
            </h1>
          </div>
        </div>

        <nav className="flex-1 px-4 py-8 flex flex-col gap-1.5 overflow-y-auto">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-4 mt-2">
            Platform
          </div>

          <NavItem icon={Database} label="Data Explorer" to="/tenant/explorer" />
          <NavItem icon={Users} label="Trading Partners" to="/tenant/partners" />
          <NavItem icon={Network} label="EDI Headers" to="/tenant/edi_headers" />
          <NavItem icon={Network} label="Routes" to="/tenant/routes" />

          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-4 mt-6">
            Tools
          </div>
          <NavItem icon={Wrench} label="EDI Tools" to="/tenant/edi_tool" />

          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-4 mt-8">
            Settings
          </div>
          <NavGroup icon={Terminal} label="Developers">
            <NavItem icon={Network} label="Webhooks" to="/tenant/webhooks" indent={true} />
            <NavItem icon={Settings} label="API Access" to="/tenant/developers" indent={true} />
          </NavGroup>

          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-4 mt-8">
            Organization
          </div>
          <NavItem icon={Users} label="Members" to="/tenant/users" />
        </nav>

        <div className="p-4 border-t border-slate-100">
          <div className="flex items-center gap-3 p-3 rounded-xl bg-white border border-slate-200/50 transition-all hover:border-slate-300 shadow-sm">
            <div className="w-10 h-10 rounded-full bg-indigo-50 text-indigo-700 flex items-center justify-center font-bold border border-indigo-100">
              {auth.user?.profile.email?.charAt(0).toUpperCase() || 'U'}
            </div>
            <div className="flex-1 overflow-hidden">
              <p className="text-sm font-medium text-slate-900 truncate">
                {auth.user?.profile.email}
              </p>
              <p className="text-xs text-slate-500 truncate">Administrator</p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => void auth.signoutRedirect()}
              className="text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg"
            >
              <LogOut className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 ml-72 flex flex-col min-h-screen">
        <header className="h-20 bg-white/80 backdrop-blur-md border-b border-slate-200/60 sticky top-0 z-40 px-8 flex items-center justify-end shadow-sm">
          {tenantId && canonicalUserId && auth.user?.access_token && (
            <NotificationBell
              tenantId={tenantId}
              userId={canonicalUserId}
              accessToken={auth.user.access_token}
              apiUrl={
                `${import.meta.env.VITE_UCP_API_URL || 'http://localhost:8000'}`.replace(
                  /\/+$/,
                  '',
                ) + '/api/v1/notifications'
              }
            />
          )}
        </header>
        <div className="flex-1 max-w-[1400px] w-full mx-auto p-8 lg:p-12">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
