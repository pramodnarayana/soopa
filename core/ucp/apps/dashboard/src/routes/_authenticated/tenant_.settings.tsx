import { createFileRoute, Outlet, redirect } from '@tanstack/react-router';
import { SettingsLayout } from '../../components/layout/SettingsLayout';

export const Route = createFileRoute('/_authenticated/tenant_/settings')({
  beforeLoad: ({ location }) => {
    // If they hit the root settings route, redirect to the first actual page
    if (location.pathname === '/tenant/settings' || location.pathname === '/tenant/settings/') {
      throw redirect({
        to: '/tenant/settings/notifications/preferences',
      });
    }
  },
  component: () => (
    <SettingsLayout>
      <Outlet />
    </SettingsLayout>
  ),
});
