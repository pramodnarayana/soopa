import { Toaster } from '@soopa/ui';
import { Button } from '@soopa/ui/components/ui/button';
import { createRootRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';

export const Route = createRootRoute({
  component: RootComponent,
});

export function RootComponent() {
  const auth = useAuth();

  // Global authentication error boundary
  if (auth.error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 gap-4">
        <div className="bg-white p-8 rounded-2xl shadow-sm border border-red-100 max-w-md w-full text-center">
          <div className="w-12 h-12 bg-red-100 text-red-600 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-slate-900 mb-2">Authentication Error</h1>
          <p className="text-slate-500 mb-6 text-sm">{auth.error.message}</p>
          <Button onClick={() => auth.signinRedirect()} className="w-full">
            Try Again
          </Button>
        </div>
      </div>
    );
  }

  // Render the child routes (either _marketing or _app)
  return (
    <div className="font-sans antialiased text-slate-900 min-h-screen">
      <Outlet />
      <Toaster />
    </div>
  );
}
