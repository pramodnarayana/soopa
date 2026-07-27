import { createFileRoute } from '@tanstack/react-router';

export const Route = createFileRoute('/_authenticated/platform/users')({
  component: PlatformUsersPage,
});

function PlatformUsersPage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold mb-4">Platform Users</h1>
      <p className="text-slate-500">Manage global platform administrators and users.</p>
      <div className="mt-8 p-12 text-center border-2 border-dashed border-slate-200 rounded-xl bg-slate-50">
        <p className="text-slate-400">Coming soon in the next release.</p>
      </div>
    </div>
  );
}
