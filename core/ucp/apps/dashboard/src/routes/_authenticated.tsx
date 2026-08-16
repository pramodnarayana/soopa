import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { apiClient } from '@/lib/api-client';
import { AuthorizationProvider } from '../contexts/AuthorizationContext';

export const Route = createFileRoute('/_authenticated')({
  component: AuthenticatedLayout,
});

function AuthenticatedLayout() {
  const auth = useAuth();

  // Keep apiClient in sync with auth state
  if (auth.user?.access_token) {
    apiClient.setToken(auth.user.access_token);
  } else {
    apiClient.setToken(null);
  }

  if (auth.isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-6">
          <div className="w-12 h-12 rounded-full border-4 border-indigo-100 border-t-indigo-600 animate-spin" />
          <p className="text-slate-500 font-medium animate-pulse tracking-wide">
            Authenticating Securely...
          </p>
        </div>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 gap-4">
        <div className="bg-white p-8 rounded-2xl shadow-sm border border-slate-100 max-w-md w-full text-center">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 flex items-center justify-center shadow-md shadow-indigo-500/20 mx-auto mb-6">
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
          <h1 className="text-2xl font-bold text-slate-900 mb-2">Soopa Platform</h1>
          <p className="text-slate-500 mb-8 text-sm">
            Central command and control for enterprise tenants.
          </p>
          <button
            onClick={() => void auth.signinRedirect()}
            className="w-full bg-indigo-600 text-white font-semibold py-2.5 px-4 rounded-xl hover:bg-indigo-700 transition-colors shadow-sm"
          >
            Login with Zitadel
          </button>
        </div>
      </div>
    );
  }

  return (
    <AuthorizationProvider>
      <Outlet />
    </AuthorizationProvider>
  );
}
