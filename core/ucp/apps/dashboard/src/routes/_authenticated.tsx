import { Button } from '@soopa/ui';
import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { AuthorizationProvider } from '../contexts/AuthorizationContext';
import { UcpApiClientProvider } from '../contexts/UcpApiClientContext';

export const Route = createFileRoute('/_authenticated')({
  component: AuthenticatedLayout,
});

function AuthenticatedLayout() {
  const auth = useAuth();

  if (auth.isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-6">
          <div className="h-12 w-12 animate-spin rounded-full border-4 border-indigo-100 border-t-indigo-600" />
          <p className="animate-pulse font-medium tracking-wide text-slate-500">
            Authenticating Securely...
          </p>
        </div>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50">
        <div className="w-full max-w-md rounded-2xl border border-slate-100 bg-white p-8 text-center shadow-sm">
          <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 shadow-md shadow-indigo-500/20">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="24"
              height="24"
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
          <h1 className="mb-2 text-2xl font-bold text-slate-900">Soopa Platform</h1>
          <p className="mb-8 text-sm text-slate-500">
            Central command and control for enterprise tenants.
          </p>
          <Button
            type="button"
            onClick={() => void auth.signinRedirect()}
            className="w-full rounded-xl bg-indigo-600 px-4 py-2.5 font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700"
          >
            Login with Zitadel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <UcpApiClientProvider token={auth.user?.access_token ?? null}>
      <AuthorizationProvider>
        <Outlet />
      </AuthorizationProvider>
    </UcpApiClientProvider>
  );
}
