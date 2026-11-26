import { Toaster } from '@soopa/ui/components/ui/sonner';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createRootRoute, Outlet } from '@tanstack/react-router';
import { AuthProvider } from '@/contexts/AuthProvider';

const queryClient = new QueryClient();

export const Route = createRootRoute({
  component: () => (
    <AuthProvider>
      <QueryClientProvider client={queryClient}>
        <Outlet />
        <Toaster />
      </QueryClientProvider>
    </AuthProvider>
  ),
});
