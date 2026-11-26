import { UserManager, type UserManagerSettings } from 'oidc-client-ts';
import { getUcpApiUrl } from './auth';

export const AUTH_SESSION_TARGET_STORAGE_KEY = 'soopa.auth.session_target';
export const AUTH_CALLBACK_ERROR_STORAGE_KEY = 'soopa.auth.callback_error';

export interface HrdDiscoveryResult {
  realm: string;
  issuer: string;
  clientId: string;
  requireSso: boolean;
  ssoProvider: string | null;
  loginHint: string | null;
}

export interface AuthSessionTarget {
  authority: string;
  clientId: string;
  realm: string;
}

export type AuthOperationResult<T = undefined> =
  | { ok: true; value: T }
  | { ok: false; message: string };

/**
 * Validates that a candidate IdP authority URL strictly matches one of the
 * configured trusted issuer origins (preventing open-redirect / phishing IdP injection).
 */
export function isSafeAuthorityUrl(
  candidate: string,
  allowedAuthorities: readonly string[],
): boolean {
  try {
    const parsed = new URL(candidate);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
      return false;
    }
    return allowedAuthorities.some((allowed) => {
      try {
        return new URL(allowed).origin === parsed.origin;
      } catch {
        return false;
      }
    });
  } catch {
    return false;
  }
}

export function buildAuthProviderSettings(
  target: Pick<AuthSessionTarget, 'authority' | 'clientId'>,
  origin: string = window.location.origin,
  options?: { forceReauth?: boolean },
): UserManagerSettings {
  return {
    authority: target.authority,
    client_id: target.clientId,
    redirect_uri: `${origin}/callback`,
    post_logout_redirect_uri: origin,
    response_type: 'code',
    scope: 'openid profile email',
    ...(options?.forceReauth ? { prompt: 'login' } : {}),
    loadUserInfo: true,
  };
}

export function readActiveAuthTarget(
  fallback: AuthSessionTarget,
  storage: Storage = window.sessionStorage,
): AuthSessionTarget {
  try {
    const raw = storage.getItem(AUTH_SESSION_TARGET_STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<AuthSessionTarget>;
    if (
      typeof parsed.authority === 'string' &&
      parsed.authority.trim().length > 0 &&
      typeof parsed.clientId === 'string' &&
      parsed.clientId.trim().length > 0 &&
      isSafeAuthorityUrl(parsed.authority.trim(), [fallback.authority])
    ) {
      return {
        authority: parsed.authority.trim(),
        clientId: parsed.clientId.trim(),
        realm: typeof parsed.realm === 'string' ? parsed.realm.trim() : fallback.realm,
      };
    }
    return fallback;
  } catch {
    return fallback;
  }
}

export function writeActiveAuthTarget(
  target: AuthSessionTarget,
  storage: Storage = window.sessionStorage,
): void {
  storage.setItem(AUTH_SESSION_TARGET_STORAGE_KEY, JSON.stringify(target));
}

export function clearActiveAuthTarget(storage: Storage = window.sessionStorage): void {
  storage.removeItem(AUTH_SESSION_TARGET_STORAGE_KEY);
}

export function writeAuthCallbackError(
  message: string,
  storage: Storage = window.sessionStorage,
): void {
  storage.setItem(AUTH_CALLBACK_ERROR_STORAGE_KEY, message);
}

export function consumeAuthCallbackError(storage: Storage = window.sessionStorage): string | null {
  try {
    const message = storage.getItem(AUTH_CALLBACK_ERROR_STORAGE_KEY);
    if (message) {
      storage.removeItem(AUTH_CALLBACK_ERROR_STORAGE_KEY);
    }
    return message;
  } catch {
    return null;
  }
}

export async function discoverHomeRealm(
  email: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AuthOperationResult<HrdDiscoveryResult>> {
  const normalized = email.trim().toLowerCase();
  try {
    const response = await fetchImpl(`${getUcpApiUrl()}/auth/hrd`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: normalized }),
    });

    if (response.status === 429) {
      return {
        ok: false,
        message: 'Too many sign-in attempts. Please wait a moment and try again.',
      };
    }

    if (!response.ok) {
      return {
        ok: false,
        message: `Sign-in discovery failed (${response.status}). Please try again.`,
      };
    }

    const data = (await response.json()) as Partial<HrdDiscoveryResult>;
    if (!data.issuer || !data.clientId || !data.realm) {
      return {
        ok: false,
        message: 'Sign-in discovery returned an incomplete identity configuration.',
      };
    }

    return {
      ok: true,
      value: {
        realm: data.realm,
        issuer: data.issuer,
        clientId: data.clientId,
        requireSso: Boolean(data.requireSso),
        ssoProvider: data.ssoProvider ?? null,
        loginHint: data.loginHint ?? normalized,
      },
    };
  } catch {
    return {
      ok: false,
      message: 'Unable to reach sign-in service. Please try again.',
    };
  }
}

export async function startHrdSignIn(
  result: HrdDiscoveryResult,
  allowedAuthorities: readonly string[],
): Promise<AuthOperationResult> {
  if (!isSafeAuthorityUrl(result.issuer, allowedAuthorities)) {
    return {
      ok: false,
      message: 'Sign-in provider URL failed security validation.',
    };
  }

  const target: AuthSessionTarget = {
    authority: result.issuer,
    clientId: result.clientId,
    realm: result.realm,
  };
  writeActiveAuthTarget(target);

  try {
    const userManager = new UserManager(buildAuthProviderSettings(target));
    const extraQueryParams: Record<string, string> = {};
    if (result.loginHint) {
      extraQueryParams.login_hint = result.loginHint;
    }

    await userManager.signinRedirect({
      extraQueryParams,
    });
    return { ok: true, value: undefined };
  } catch (err) {
    clearActiveAuthTarget();
    return {
      ok: false,
      message: err instanceof Error ? err.message : 'Unable to redirect to identity provider.',
    };
  }
}
