import { createFileRoute } from '@tanstack/react-router';
import { SchedulerDashboard } from '@/features/platform/components/SchedulerDashboard';

export const Route = createFileRoute('/platform/scheduler')({
  component: SchedulerDashboard,
});
