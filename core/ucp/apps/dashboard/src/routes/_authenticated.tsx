import { createFileRoute, Outlet } from '@tanstack/react-router';
import { useAuth } from 'react-oidc-context';
import { EmailFirstLoginScreen } from '../components/auth/EmailFirstLoginScreen';
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
    return <EmailFirstLoginScreen />;
  }

  return (
    <UcpApiClientProvider token={auth.user?.access_token ?? null}>
      <AuthorizationProvider>
        <Outlet />
      </AuthorizationProvider>
    </UcpApiClientProvider>
  );
}
