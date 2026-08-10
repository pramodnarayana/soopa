import { NavGroup } from '@soopa/ui/components/ui/NavGroup';
import { createFileRoute, Navigate, Outlet } from '@tanstack/react-router';
import { Clock, LayoutDashboard, LogOut, Network, Settings, Users } from 'lucide-react';
import { useAuth } from 'react-oidc-context';
import { AppLayout } from '@/components/layout/AppLayout';
import { NavItem } from '@/components/layout/NavItem';
import { useIsPlatformAdmin } from '@/hooks/useIsPlatformAdmin';

export const Route = createFileRoute('/_authenticated/platform')({
  component: PlatformLayoutGuard,
});

function PlatformSidebar() {
  return (
    <>
      <div className="text-[18px] font-bold text-slate-400 uppercase tracking-widest mb-3 px-4 mt-2">
        Platform Control
      </div>
      <NavItem icon={LayoutDashboard} label="Overview" to="/platform" exact />

      <div className="text-[18px] font-bold text-slate-400 uppercase tracking-widest mb-3 px-4 mt-8">
        System Admin
      </div>
      <NavItem icon={Network} label="Tenants" to="/platform/tenants" />
      <NavItem icon={Users} label="Platform Users" to="/platform/users" />
      <NavItem icon={Clock} label="Scheduler" to="/platform/scheduler" />

      <div className="text-[18px] font-bold text-slate-400 uppercase tracking-widest mb-3 px-4 mt-8">
        Global Settings
      </div>
      <NavGroup icon={Settings} label="EDI Settings" defaultExpanded={true}>
        <NavItem icon={Users} label="AS2 Partners" to="/platform/edi/as2partners" />
        <NavItem icon={Network} label="AS2 Partnerships" to="/platform/edi/as2partnerships" />
      </NavGroup>
    </>
  );
}

function PlatformLayoutGuard() {
  const auth = useAuth();
  const isPlatformAdmin = useIsPlatformAdmin();

  if (!isPlatformAdmin) {
    return <Navigate to="/tenant" replace />;
  }

  return (
    <AppLayout
      sidebarHeader={
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center shadow-sm">
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
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            Soopa <span className="font-medium text-muted-foreground">Platform</span>
          </h1>
        </div>
      }
      sidebarNavigation={<PlatformSidebar />}
      userProfile={
        <div className="flex items-center gap-4 p-4 rounded-xl hover:bg-slate-50 transition-colors group">
          <div className="w-12 h-12 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-lg">
            {auth.user?.profile.email?.charAt(0).toUpperCase() || 'P'}
          </div>
          <div className="flex-1 overflow-hidden">
            <p className="text-base font-semibold text-foreground truncate">
              {auth.user?.profile.email}
            </p>
            <p className="text-xs text-muted-foreground truncate uppercase tracking-widest mt-1">
              Platform Admin
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
  );
}
