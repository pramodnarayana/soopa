import { type ReactNode, useMemo } from 'react';
import { AuthProvider as OidcProvider } from 'react-oidc-context';
import { config } from '@/lib/config';
import {
  type AuthSessionTarget,
  buildAuthProviderSettings,
  clearActiveAuthTarget,
  readActiveAuthTarget,
} from '@/lib/hrd';

const { authority, clientId } = config.identity;

if (!authority || !clientId) {
  throw new Error(
    'FATAL: Missing required Identity environment variables (VITE_IDENTITY_API_URL, VITE_IDENTITY_UCP_WEB_CLIENT_ID). Check the root .env file.',
  );
}

const DEFAULT_AUTH_TARGET: AuthSessionTarget = {
  authority,
  clientId,
  realm: '',
};

interface AuthProviderProps {
  children: ReactNode;
}

/**
 * Capability-level authentication provider for the Dashboard.
 *
 * Hydrates the active Home Realm Discovery (HRD) session target so the
 * authorization redirect, /callback exchange, silent refresh, and signout
 * remain consistent across realms while keeping protocol details internal.
 */
export function AuthProvider({ children }: AuthProviderProps) {
  const providerSettings = useMemo(() => {
    const activeTarget = readActiveAuthTarget(DEFAULT_AUTH_TARGET);
    return buildAuthProviderSettings(activeTarget);
  }, []);

  return (
    <OidcProvider
      {...providerSettings}
      onRemoveUser={() => {
        clearActiveAuthTarget();
      }}
    >
      {children}
    </OidcProvider>
  );
}
