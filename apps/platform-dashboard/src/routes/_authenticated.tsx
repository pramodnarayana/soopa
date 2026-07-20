import { createFileRoute, Outlet, Link } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/_authenticated')({
  component: AuthenticatedLayout,
});

function AuthenticatedLayout() {
  const auth = useAuth();

  if (auth.isLoading) {
    return <div className="p-8">Loading Authentication...</div>;
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4">Soopa UCP Developer Portal</h1>
          <button
            onClick={() => void auth.signinRedirect()}
            className="bg-black text-white px-6 py-2 rounded-md hover:bg-gray-800 transition"
          >
            Login with Zitadel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-64 bg-black text-white p-6 flex flex-col">
        <h2 className="text-xl font-bold mb-8">Soopa UCP</h2>
        <nav className="flex-1 space-y-4">
          <Link to="/" className="block text-gray-300 hover:text-white transition">Dashboard</Link>
          <Link to="/tenants" className="block text-gray-300 hover:text-white transition">Tenants</Link>
          <a href="/scheduler" className="block text-gray-300 hover:text-white transition">Scheduler</a>
        </nav>
        <div className="mt-auto">
          <p className="text-sm text-gray-400 truncate mb-4">{auth.user?.profile.email}</p>
          <button 
            onClick={() => void auth.signoutRedirect()}
            className="text-sm text-red-400 hover:text-red-300 transition"
          >
            Logout
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-gray-50 p-8">
        <Outlet />
      </main>
    </div>
  );
}
