import { createRootRoute, Outlet } from '@tanstack/react-router';
import { AuthProvider } from 'react-oidc-context';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const queryClient = new QueryClient();

// In a real app, these come from environment variables
const oidcConfig = {
  authority: "http://localhost:8080", // Zitadel Local URL
  client_id: "developer-portal@soopa.localhost",
  redirect_uri: "http://localhost:5173/callback",
  response_type: "code",
  scope: "openid profile email",
};

export const Route = createRootRoute({
  component: () => (
    <AuthProvider {...oidcConfig}>
      <QueryClientProvider client={queryClient}>
        <Outlet />
      </QueryClientProvider>
    </AuthProvider>
  ),
});
