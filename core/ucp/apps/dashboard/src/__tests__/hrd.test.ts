import { describe, expect, it, vi } from 'vitest';
import {
  type AuthSessionTarget,
  buildAuthProviderSettings,
  clearActiveAuthTarget,
  consumeAuthCallbackError,
  discoverHomeRealm,
  isSafeAuthorityUrl,
  readActiveAuthTarget,
  writeActiveAuthTarget,
  writeAuthCallbackError,
} from '../lib/hrd';

function createMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
  };
}

describe('Home Realm Discovery (HRD) auth session helpers', () => {
  it('validates issuer authority URLs strictly against the trusted authority allowlist', () => {
    const allowed = ['https://identity.flowwolf.io', 'http://localhost:8080'];
    expect(isSafeAuthorityUrl('https://identity.flowwolf.io', allowed)).toBe(true);
    expect(isSafeAuthorityUrl('http://localhost:8080', allowed)).toBe(true);
    expect(isSafeAuthorityUrl('https://evil-phishing-idp.example', allowed)).toBe(false);
    expect(isSafeAuthorityUrl('http://evil.example', allowed)).toBe(false);
    expect(isSafeAuthorityUrl('javascript:alert(1)', allowed)).toBe(false);
  });

  it('persists, reads, and clears the active realm auth target in storage', () => {
    const storage = createMemoryStorage();
    const fallback: AuthSessionTarget = {
      authority: 'http://localhost:8080',
      clientId: 'default_cid',
      realm: 'soopa-global',
    };

    expect(readActiveAuthTarget(fallback, storage)).toEqual(fallback);

    const platformTarget: AuthSessionTarget = {
      authority: 'http://localhost:8080',
      clientId: 'soopa_platform_admin_cid',
      realm: 'soopa-platform',
    };
    writeActiveAuthTarget(platformTarget, storage);
    expect(readActiveAuthTarget(fallback, storage)).toEqual(platformTarget);

    clearActiveAuthTarget(storage);
    expect(readActiveAuthTarget(fallback, storage)).toEqual(fallback);
  });

  it('stores and consumes callback error messages once', () => {
    const storage = createMemoryStorage();
    writeAuthCallbackError('Access denied by identity provider.', storage);
    expect(consumeAuthCallbackError(storage)).toBe('Access denied by identity provider.');
    expect(consumeAuthCallbackError(storage)).toBeNull();
  });

  it('builds IdP-agnostic OAuth 2.1 PKCE settings without forcing re-login by default', () => {
    const ssoSettings = buildAuthProviderSettings(
      {
        authority: 'http://localhost:8080',
        clientId: 'soopa_dashboard_cid-org-soopa-global',
      },
      'http://localhost:5173',
    );

    expect(ssoSettings.authority).toBe('http://localhost:8080');
    expect(ssoSettings.client_id).toBe('soopa_dashboard_cid-org-soopa-global');
    expect(ssoSettings.redirect_uri).toBe('http://localhost:5173/callback');
    expect(ssoSettings.response_type).toBe('code');
    expect(ssoSettings.scope).toBe('openid profile email');
    expect(ssoSettings.prompt).toBeUndefined();

    const stepUpSettings = buildAuthProviderSettings(
      {
        authority: 'http://localhost:8080',
        clientId: 'soopa_platform_admin_cid',
      },
      'http://localhost:5173',
      { forceReauth: true },
    );
    expect(stepUpSettings.prompt).toBe('login');
  });

  it('returns first-class Result values for HRD success, rate limit, and HTTP failure without throwing', async () => {
    const mockOkFetch = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          realm: 'soopa-platform',
          issuer: 'http://localhost:8080',
          clientId: 'soopa_platform_admin_cid',
          requireSso: false,
          ssoProvider: null,
          loginHint: 'admin@flowwolf.io',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const okResult = await discoverHomeRealm('  Admin@FlowWolf.io ', mockOkFetch);
    expect(okResult.ok).toBe(true);
    if (okResult.ok) {
      expect(okResult.value.realm).toBe('soopa-platform');
      expect(okResult.value.clientId).toBe('soopa_platform_admin_cid');
    }

    const mock429Fetch = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response('Too Many Requests', { status: 429 }));
    const limitedResult = await discoverHomeRealm('alice@acme.com', mock429Fetch);
    expect(limitedResult.ok).toBe(false);
    if (!limitedResult.ok) {
      expect(limitedResult.message).toContain('Too many sign-in attempts');
    }

    const mockErrFetch = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response('Service Unavailable', { status: 503 }));
    const errResult = await discoverHomeRealm('alice@acme.com', mockErrFetch);
    expect(errResult.ok).toBe(false);
    if (!errResult.ok) {
      expect(errResult.message).toContain('503');
    }
  });
});
