import { createFileRoute, Navigate } from '@tanstack/react-router';
import { useIsPlatformAdmin } from '../../hooks/useIsPlatformAdmin';

export const Route = createFileRoute('/_authenticated/')({
  component: DashboardSwitch,
});

function DashboardSwitch() {
  const { isPlatformAdmin, isLoading } = useIsPlatformAdmin();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-6">
          <div className="w-12 h-12 rounded-full border-4 border-indigo-100 border-t-indigo-600 animate-spin" />
        </div>
      </div>
    );
  }

  if (isPlatformAdmin) {
    return <Navigate to="/platform" replace />;
  }

  return <Navigate to="/tenant" replace />;
}
