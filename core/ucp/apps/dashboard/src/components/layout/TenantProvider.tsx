import { NotificationBell } from '@soopa/ui';
import { LogOut } from 'lucide-react';
import type { ReactNode } from 'react';
import { useAuth } from 'react-oidc-context';
import { TenantContext } from '../../contexts/TenantContext';
import { useGetTenant } from '../../domains/tenants/api/queries';
import { useAuthUser } from '../../hooks/useAuthUser';
import { resolveTenantId } from '../../lib/auth';
import { getApiUrl } from '../../lib/config';

const logger = console;

export interface TenantProviderProps {
  children: (props: {
    sidebarHeader: ReactNode;
    userProfile: ReactNode;
    headerContent: ReactNode;
    tenantSubscriptions: string[];
  }) => ReactNode;
}

export function TenantProvider({ children }: TenantProviderProps) {
  const auth = useAuth();
  const token = auth.user?.access_token ?? '';
  const tenantId = resolveTenantId(token, auth.user?.profile ?? {});
  // Use the canonical platform user ID (usr_...) from our own /auth/me endpoint,
  // NOT the raw OIDC `sub` from the JWT (which is the Zitadel numeric IDP user ID).
  // This ensures our IDOR guards comparing against identity.subject always pass.
  const { data: authUser } = useAuthUser();
  const canonicalUserId = authUser?.subject ?? '';

  const { data: tenant } = useGetTenant(tenantId ?? '');

  if (!tenantId) {
    logger.error('Tenant ID resolution failed', {
      hasToken: !!token,
      hasUser: !!auth.user,
      profileKeyCount: Object.keys(auth.user?.profile ?? {}).length,
    });

    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/40">
        <div className="max-w-md rounded-lg border border-border bg-card p-6 shadow-xs">
          <h1 className="mb-2 text-lg font-semibold text-foreground">Configuration Error</h1>
          <p className="mb-4 text-sm text-muted-foreground">
            Your account is not properly configured. Please contact your administrator.
          </p>
          <button
            type="button"
            onClick={() => void auth.signoutRedirect()}
            className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-3.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Sign Out
          </button>
        </div>
      </div>
    );
  }

  const sidebarHeader = (
    <div className="flex w-full items-center gap-2.5">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1-1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" />
        </svg>
      </div>
      <span className="truncate text-sm font-semibold tracking-tight text-foreground">
        {tenant ? tenant.name : 'Loading...'}
      </span>
    </div>
  );

  const userProfile = (
    <div className="group flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-sidebar-accent">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
        {auth.user?.profile.email?.charAt(0).toUpperCase() || 'T'}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-foreground">{auth.user?.profile.email}</p>
        <p className="truncate text-[11px] text-muted-foreground">Tenant Admin</p>
      </div>
      <button
        type="button"
        onClick={() => void auth.signoutRedirect()}
        aria-label="Sign out"
        className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <LogOut className="h-4 w-4" />
      </button>
    </div>
  );

  const finalTenantId = tenant?.id ?? tenantId ?? '';

  const headerContent = (
    <NotificationBell
      tenantId={tenant?.id ?? ''}
      userId={canonicalUserId}
      accessToken={token}
      apiUrl={getApiUrl('/api/v1/notifications')}
    />
  );

  return (
    <TenantContext.Provider
      value={{
        tenantId: finalTenantId,
        token,
      }}
    >
      {children({
        sidebarHeader,
        userProfile,
        headerContent,
        tenantSubscriptions: tenant?.subscriptions ?? [],
      })}
    </TenantContext.Provider>
  );
}
