import { useAuth } from 'react-oidc-context';

export function useAuthRoles(): Record<string, unknown> {
  const auth = useAuth();
  return (auth.user?.profile['urn:zitadel:iam:org:project:roles'] as Record<string, unknown>) || {};
}

export function useIsPlatformAdmin(): boolean {
  const roles = useAuthRoles();
  return 'PlatformAdmin' in roles;
}
