import { Toaster } from '@soopa/ui/components/ui/sonner';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRootRoute, Outlet } from '@tanstack/react-router';
import { AuthProvider } from 'react-oidc-context';

import { config } from '@/lib/config';

const queryClient = new QueryClient();

const { authority, clientId, projectId } = config.identity;

if (!authority || !clientId || !projectId) {
  throw new Error(
    'FATAL: Missing required Identity environment variables (VITE_IDENTITY_API_URL, VITE_IDENTITY_UCP_WEB_CLIENT_ID, VITE_IDENTITY_UCP_PROJECT_ID). Check the root .env file.',
  );
}

const oidcConfig = {
  authority,
  client_id: clientId,
  redirect_uri: `${window.location.origin}/callback`,
  response_type: 'code',
  scope: `openid profile email urn:zitadel:iam:org:project:roles urn:zitadel:iam:org:id urn:zitadel:iam:org:project:id:${projectId}:roles urn:zitadel:iam:org:project:id:${projectId}:aud`,
  prompt: 'login',
  loadUserInfo: true,
};

export const Route = createRootRoute({
  component: () => (
    <AuthProvider {...oidcConfig}>
      <QueryClientProvider client={queryClient}>
        <Outlet />
        <Toaster />
      </QueryClientProvider>
    </AuthProvider>
  ),
});
