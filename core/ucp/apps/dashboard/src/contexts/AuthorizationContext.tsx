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
  const { data: authUser, isLoading } = useAuthUser();

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
