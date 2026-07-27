import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRootRoute, Outlet } from '@tanstack/react-router';
import { AuthProvider } from 'react-oidc-context';
import { Toaster } from '@/components/ui/sonner';

const queryClient = new QueryClient();

const oidcConfig = {
  authority:
    (import.meta.env as unknown as Record<string, string>).VITE_ZITADEL_AUTHORITY ||
    'http://ucp.localhost:8080',
  client_id:
    (import.meta.env as unknown as Record<string, string>).VITE_ZITADEL_CLIENT_ID ||
    '383492001540145155',
  redirect_uri: `${window.location.origin}/callback`,
  response_type: 'code',
  scope:
    'openid profile email urn:zitadel:iam:org:project:roles urn:zitadel:iam:org:id urn:zitadel:iam:org:project:id:383492001305264131:roles',
  prompt: 'login',
  loadUserInfo: true,
};

export const Route = createRootRoute({
  component: () => (
    <AuthProvider {...oidcConfig}>
      <QueryClientProvider client={queryClient}>
        <Outlet />
        <Toaster position="top-right" />
      </QueryClientProvider>
    </AuthProvider>
  ),
});
