import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/platform/')({
  component: PlatformDashboard,
});

function PlatformDashboard() {
  return (
    <div>
      <h1 className="text-3xl font-bold tracking-tight mb-8">Dashboard</h1>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
          <h3 className="text-gray-500 font-medium">Total Tenants</h3>
          <p className="text-3xl font-bold mt-2 text-gray-400">—</p>
        </div>

        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
          <h3 className="text-gray-500 font-medium">Active API Keys</h3>
          <p className="text-3xl font-bold mt-2 text-gray-400">—</p>
        </div>

        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm">
          <h3 className="text-gray-500 font-medium">Failed Jobs (24h)</h3>
          <p className="text-3xl font-bold mt-2 text-gray-400">—</p>
        </div>
      </div>
    </div>
  );
}
