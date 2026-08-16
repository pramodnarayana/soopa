import { createContext, ReactNode, useContext } from 'react';
import { useAuthUser } from '../hooks/useAuthUser';

export interface AuthorizationContextValue {
  capabilities: string[];
  isPlatformAdmin: boolean;
}

export const AuthorizationContext = createContext<AuthorizationContextValue | null>(null);

export function useAuthorizationContext(): AuthorizationContextValue {
  const ctx = useContext(AuthorizationContext);
  if (!ctx) {
    throw new Error(
      'useAuthorizationContext must be used inside <AuthorizationProvider>. ' +
        'Ensure this component is rendered within the authenticated layout.',
    );
  }
  return ctx;
}

export function AuthorizationProvider({ children }: { children: ReactNode }) {
  const { data: authUser, isLoading, isError } = useAuthUser();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-6">
          <div className="w-12 h-12 rounded-full border-4 border-indigo-100 border-t-indigo-600 animate-spin" />
          <p className="text-slate-500 font-medium animate-pulse tracking-wide">Authorizing...</p>
        </div>
      </div>
    );
  }

  // Handle query failures and unauthenticated responses
  if (isError || authUser?.authenticated === false) {
    return (
      <div className="flex h-screen items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-6 max-w-md text-center">
          <div className="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center">
            <span className="text-red-600 text-2xl">!</span>
          </div>
          <div>
            <h2 className="text-xl font-semibold text-slate-900 mb-2">Authorization Failed</h2>
            <p className="text-slate-600">
              {isError
                ? 'Unable to verify your authorization. Please try refreshing the page.'
                : 'You are not authenticated. Please sign in again.'}
            </p>
          </div>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const capabilities = authUser?.capabilities ?? [];
  const isPlatformAdmin = authUser?.isPlatformAdmin ?? false;

  return (
    <AuthorizationContext.Provider
      value={{
        capabilities,
        isPlatformAdmin,
      }}
    >
      {children}
    </AuthorizationContext.Provider>
  );
}
