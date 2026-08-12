import { createFileRoute, Outlet } from '@tanstack/react-router';
import { ArrowLeftRight, Bell, LayoutDashboard, Settings, Wrench } from 'lucide-react';
import { AppLayout } from '../../components/layout/AppLayout';
import { NavItem } from '../../components/layout/NavItem';
import { TenantProvider } from '../../components/layout/TenantProvider';

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
      <NavItem icon={Bell} label="Notifications" to="/tenant/notifications" exact />
      {isEdiSubscribed && (
        <>
          <div className="text-[18px] font-bold text-muted-foreground uppercase tracking-widest mb-3 px-4 mt-8">
            EDI
          </div>
          <NavItem icon={LayoutDashboard} label="EDI Dashboard" to="/tenant/edi" exact />
          <NavItem icon={ArrowLeftRight} label="Transactions" to="/tenant/edi/transactions" />
          <NavItem icon={Settings} label="EDI Setup" to="/tenant/edi/setup" />
          <NavItem icon={Wrench} label="EDI Tool" to="/tenant/edi/tool" />
        </>
      )}

      <div className="text-[18px] font-bold text-muted-foreground uppercase tracking-widest mb-3 px-4 mt-8">
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
