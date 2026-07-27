import { createFileRoute, Navigate } from '@tanstack/react-router';
import { useIsPlatformAdmin } from '../../hooks/useIsPlatformAdmin';

export const Route = createFileRoute('/_authenticated/')({
  component: DashboardSwitch,
});

function DashboardSwitch() {
  const isPlatformAdmin = useIsPlatformAdmin();

  if (isPlatformAdmin) {
    return <Navigate to="/platform" replace />;
  }

  return <Navigate to="/tenant" replace />;
}
