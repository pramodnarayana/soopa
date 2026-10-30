import { createFileRoute, Outlet } from '@tanstack/react-router';
import {
  Activity,
  ArrowLeftRight,
  Bell,
  Cable,
  Compass,
  GitMerge,
  LayoutDashboard,
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
    <>
      <div className="mb-3 mt-2 px-4 text-lg font-bold tracking-widest text-muted-foreground uppercase">
        Overview
      </div>
      <NavItem icon={LayoutDashboard} label="Dashboard" to="/tenant" exact />
      <NavItem icon={Bell} label="Notifications" to="/tenant/notifications" exact />
      {isEdiSubscribed && (
        <>
          <div className="mb-3 mt-8 px-4 text-lg font-bold tracking-widest text-muted-foreground uppercase">
            EDI
          </div>
          <NavItem icon={LayoutDashboard} label="EDI Dashboard" to="/tenant/edi" exact />
          <NavItem icon={ArrowLeftRight} label="Transactions" to="/tenant/edi/transactions" />
          <NavItem icon={Settings} label="EDI Setup" to="/tenant/edi/setup" />
          <NavItem icon={Wrench} label="EDI Tool" to="/tenant/edi/tool" />
        </>
      )}

      {isIpSubscribed && (
        <>
          <div className="mb-3 mt-8 px-4 text-lg font-bold tracking-widest text-muted-foreground uppercase">
            Integration Platform
          </div>
          <NavItem icon={Compass} label="Command Center" to="/tenant/ip" exact />
          <NavItem icon={Activity} label="Support Traces" to="/tenant/ip/traces" />
          <NavItem icon={Cable} label="Connections" to="/tenant/ip/connections" />
          <NavItem icon={GitMerge} label="Transformations" to="/tenant/ip/transformations" />
          <NavItem icon={Workflow} label="Stitches" to="/tenant/ip/stitches" />
        </>
      )}

      <div className="mb-3 mt-8 px-4 text-lg font-bold tracking-widest text-muted-foreground uppercase">
        Configuration
      </div>
      <NavItem icon={Settings} label="Settings" to="/tenant/settings" />
    </>
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
