import { createRoute, Navigate, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { Button } from '@/components/ui/button';
import { Route as rootRoute } from './__root';

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  id: 'marketing',
  component: MarketingLayout,
});

export function MarketingLayout() {
  const auth = useAuth();

  if (auth.isAuthenticated) {
    // If they have a token, we don't know their role yet without fetching it.
    // The easiest way is to let the tenant dashboard (which acts as a router) handle it,
    // or we redirect to /tenant/dashboard which redirects them to /platform/dashboard if they are an admin.
    return <Navigate to="/tenant/dashboard" replace />;
  }

  const handleSignUp = () => {
    void auth.signinRedirect({ extraQueryParams: { prompt: 'create' } });
  };

  return (
    <div className="min-h-screen bg-white text-slate-900 flex flex-col font-sans">
      {/* Crisp White Navigation */}
      <header className="sticky top-0 z-50 w-full border-b border-slate-200 bg-white/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded bg-slate-900 flex items-center justify-center">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="white"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
              </svg>
            </div>
            <span className="text-lg font-bold tracking-tight text-slate-900">EDI AS2</span>
          </div>

          <nav className="flex items-center gap-4">
            <Button
              variant="ghost"
              className="text-slate-600 hover:text-slate-900 hover:bg-slate-100 font-medium"
              onClick={() => void auth.signinRedirect()}
            >
              Log in
            </Button>
            <Button
              className="bg-slate-900 hover:bg-slate-800 text-white font-medium shadow-sm"
              onClick={handleSignUp}
            >
              Sign up
            </Button>
          </nav>
        </div>
      </header>

      {/* Page Content */}
      <main className="flex-1 flex flex-col">
        <Outlet />
      </main>

      {/* Minimal Footer */}
      <footer className="border-t border-slate-200 py-12 bg-slate-50">
        <div className="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center justify-between text-sm text-slate-500">
          <p>&copy; {new Date().getFullYear()} Soopa Platform.</p>
          <div className="flex gap-6 mt-4 md:mt-0">
            <span className="text-slate-400">Documentation</span>
            <span className="text-slate-400">Status</span>
            <span className="text-slate-400">Terms</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
