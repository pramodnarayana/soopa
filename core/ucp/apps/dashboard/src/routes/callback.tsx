import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { useEffect } from 'react';
import { useAuth } from 'react-oidc-context';

export const Route = createFileRoute('/callback')({
  component: CallbackComponent,
});

function CallbackComponent() {
  const auth = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (auth.isAuthenticated) {
      void navigate({ to: '/tenants', replace: true });
    } else if (auth.error) {
      console.error('OIDC Auth Error:', auth.error);
      void navigate({ to: '/', replace: true });
    }
  }, [auth.isAuthenticated, auth.error, navigate]);

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-gray-50 dark:bg-gray-900">
      <div className="text-center space-y-4">
        <div className="animate-spin h-10 w-10 border-4 border-indigo-500 border-t-transparent rounded-full mx-auto"></div>
        <p className="text-gray-600 dark:text-gray-300">Completing login...</p>
      </div>
    </div>
  );
}
