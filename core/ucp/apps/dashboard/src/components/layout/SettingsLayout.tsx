import { NavGroup } from '@soopa/ui/components/ui/NavGroup';
import { Link } from '@tanstack/react-router';
import { ArrowLeft, Bell, FileText, Key, Network, SlidersHorizontal, Wrench } from 'lucide-react';
import { ReactNode } from 'react';
import { AppLayout } from './AppLayout';
import { NavItem } from './NavItem';
import { TenantProvider } from './TenantProvider';

function SettingsSidebar() {
  return (
    <>
      <div className="px-4 mt-2 mb-6">
        <Link
          to="/tenant"
          className="inline-flex items-center gap-2 font-medium text-muted-foreground hover:text-foreground transition-colors group text-[17px] tracking-wide px-4 py-3"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Dashboard
        </Link>
      </div>

      <NavGroup icon={Bell} label="Notifications" defaultExpanded={false}>
        <NavItem
          icon={SlidersHorizontal}
          label="Channel Preferences"
          to="/tenant/settings/notifications/preferences"
        />
        <NavItem
          icon={FileText}
          label="Message Templates"
          to="/tenant/settings/notifications/templates"
        />
      </NavGroup>

      <NavGroup icon={Wrench} label="Developer" defaultExpanded={false}>
        <NavItem icon={Key} label="API Tokens" to="/tenant/settings/developer/api-tokens" />
        <NavItem icon={Network} label="Webhooks" to="/tenant/settings/developer/webhooks" />
      </NavGroup>
    </>
  );
}

interface SettingsLayoutProps {
  children: ReactNode;
}

export function SettingsLayout({ children }: SettingsLayoutProps) {
  return (
    <TenantProvider>
      {({ sidebarHeader, userProfile, headerContent }) => (
        <AppLayout
          sidebarHeader={sidebarHeader}
          sidebarNavigation={<SettingsSidebar />}
          userProfile={userProfile}
          headerContent={headerContent}
        >
          <div className="h-full overflow-y-auto">{children}</div>
        </AppLayout>
      )}
    </TenantProvider>
  );
}
