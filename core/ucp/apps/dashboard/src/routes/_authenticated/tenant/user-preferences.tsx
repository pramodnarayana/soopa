import { createFileRoute } from '@tanstack/react-router';
import { UserNotificationPreferencesPage } from '@/domains/notifications/components/UserNotificationPreferencesPage';

export const Route = createFileRoute('/_authenticated/tenant/user-preferences')({
  component: UserNotificationPreferencesPage,
});
