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
    <div className="space-y-4">
      <div className="space-y-0.5">
        <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">
          Platform Control
        </div>
        <NavItem icon={LayoutDashboard} label="Overview" to="/platform" exact />
      </div>

      <div className="space-y-0.5">
        <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">
          System Admin
        </div>
        <NavItem icon={Network} label="Tenants" to="/platform/tenants" />
        <NavItem icon={Users} label="Platform Users" to="/platform/users" />
        <NavItem icon={Clock} label="Scheduler" to="/platform/scheduler" />
      </div>

      <div className="space-y-0.5">
        <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">
          Global Settings
        </div>
        <NavGroup icon={Settings} label="EDI Settings" defaultExpanded={true}>
          <NavItem icon={Users} label="AS2 Partners" to="/platform/edi/as2partners" />
          <NavItem icon={Network} label="AS2 Partnerships" to="/platform/edi/as2partnerships" />
        </NavGroup>
      </div>
    </div>
  );
}

function PlatformLayoutGuard() {
  const auth = useAuth();
  const { isPlatformAdmin, isLoading } = useIsPlatformAdmin();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted border-t-foreground" />
        </div>
      </div>
    );
  }

  if (!isPlatformAdmin) {
    return <Navigate to="/tenant" replace />;
  }

  return (
    <AppLayout
      sidebarHeader={
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1-1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
            </svg>
          </div>
          <span className="truncate text-sm font-semibold tracking-tight text-foreground">
            Soopa <span className="font-normal text-muted-foreground">Platform</span>
          </span>
        </div>
      }
      sidebarNavigation={<PlatformSidebar />}
      userProfile={
        <div className="group flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-sidebar-accent">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
            {auth.user?.profile.email?.charAt(0).toUpperCase() || 'P'}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-foreground">
              {auth.user?.profile.email}
            </p>
            <p className="truncate text-[11px] text-muted-foreground">Platform Admin</p>
          </div>
          <button
            type="button"
            onClick={() => void auth.signoutRedirect()}
            aria-label="Sign out"
            className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      }
    >
      <Outlet />
    </AppLayout>
  );
}
