/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_PROXY_TARGET?: string;
  readonly VITE_UCP_API_URL?: string;
  readonly VITE_IDENTITY_API_URL?: string;
  readonly VITE_IDENTITY_UCP_PROJECT_ID?: string;
  readonly VITE_IDENTITY_UCP_WEB_CLIENT_ID?: string;
  /**
   * @deprecated Vite does not expose variables without the VITE_ prefix at runtime.
   * These are backward-compatibility shims and will always resolve to `undefined`.
   * Migrate all usages to VITE_IDENTITY_API_URL.
   */
  readonly IDENTITY_API_URL?: string;
  /**
   * @deprecated See IDENTITY_API_URL. Migrate to VITE_IDENTITY_UCP_PROJECT_ID.
   */
  readonly IDENTITY_UCP_PROJECT_ID?: string;
  /**
   * @deprecated See IDENTITY_API_URL. Migrate to VITE_IDENTITY_UCP_WEB_CLIENT_ID.
   */
  readonly IDENTITY_UCP_WEB_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
