import { Toaster } from '@soopa/ui/components/ui/sonner';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRootRoute, Outlet } from '@tanstack/react-router';
import { AuthProvider } from 'react-oidc-context';

const queryClient = new QueryClient();

const authority = (import.meta.env as unknown as Record<string, string>).ZITADEL_API_URL;
const clientId = (import.meta.env as unknown as Record<string, string>).ZITADEL_UCP_WEB_CLIENT_ID;
const projectId = (import.meta.env as unknown as Record<string, string>).ZITADEL_UCP_PROJECT_ID;

if (!authority || !clientId || !projectId) {
  throw new Error(
    'FATAL: Missing required Zitadel environment variables (ZITADEL_API_URL, ZITADEL_UCP_WEB_CLIENT_ID, ZITADEL_UCP_PROJECT_ID). Check the root .env file.',
  );
}

const oidcConfig = {
  authority,
  client_id: clientId,
  redirect_uri: `${window.location.origin}/callback`,
  response_type: 'code',
  scope: `openid profile email urn:zitadel:iam:org:project:roles urn:zitadel:iam:org:id urn:zitadel:iam:org:project:id:${projectId}:roles`,
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
