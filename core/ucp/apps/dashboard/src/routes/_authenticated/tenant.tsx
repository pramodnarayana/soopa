import { createFileRoute, Outlet } from '@tanstack/react-router';
import {
  Activity,
  ArrowLeftRight,
  BarChart3,
  Bell,
  Compass,
  GitMerge,
  LayoutDashboard,
  LayoutGrid,
  Settings,
  Workflow,
  Wrench,
} from 'lucide-react';
import { AppLayout } from '../../components/layout/AppLayout';
import { NavItem } from '../../components/layout/NavItem';
import { TenantProvider } from '../../components/layout/TenantProvider';

export const Route = createFileRoute('/_authenticated/tenant')({
  component: TenantLayout,
});

function TenantSidebar({ subscriptions }: { subscriptions: string[] }) {
  const isEdiSubscribed = subscriptions.includes('edi');
  const isIpSubscribed = subscriptions.includes('ip');

  return (
    <div className="space-y-4">
      <div className="space-y-0.5">
        <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">
          Overview
        </div>
        <NavItem icon={LayoutDashboard} label="Dashboard" to="/tenant" exact />
        <NavItem icon={Bell} label="Notifications" to="/tenant/notifications" exact />
      </div>

      {isEdiSubscribed && (
        <div className="space-y-0.5">
          <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">
            EDI
          </div>
          <NavItem icon={LayoutDashboard} label="EDI Dashboard" to="/tenant/edi" exact />
          <NavItem icon={ArrowLeftRight} label="Transactions" to="/tenant/edi/transactions" />
          <NavItem icon={Settings} label="EDI Setup" to="/tenant/edi/setup" />
          <NavItem icon={Wrench} label="EDI Tool" to="/tenant/edi/tool" />
        </div>
      )}

      {isIpSubscribed && (
        <div className="space-y-0.5">
          <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">
            Integration Platform
          </div>
          <NavItem icon={Compass} label="Command Center" to="/tenant/ip" exact />
          <NavItem icon={Activity} label="Support Traces" to="/tenant/ip/traces" />
          <NavItem icon={BarChart3} label="Interval Streams" to="/tenant/ip/intervals" />
          <NavItem icon={LayoutGrid} label="Apps" to="/tenant/ip/connections" />
          <NavItem icon={GitMerge} label="Transformations" to="/tenant/ip/transformations" />
          <NavItem icon={Workflow} label="Stitches" to="/tenant/ip/stitches" />
        </div>
      )}

      <div className="space-y-0.5">
        <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/80">
          Configuration
        </div>
        <NavItem icon={Settings} label="Settings" to="/tenant/settings" />
      </div>
    </div>
  );
}

function TenantLayout() {
  return (
    <TenantProvider>
      {({ sidebarHeader, userProfile, headerContent, tenantSubscriptions }) => (
        <AppLayout
          sidebarHeader={sidebarHeader}
          sidebarNavigation={<TenantSidebar subscriptions={tenantSubscriptions} />}
          userProfile={userProfile}
          headerContent={headerContent}
        >
          <Outlet />
        </AppLayout>
      )}
    </TenantProvider>
  );
}
