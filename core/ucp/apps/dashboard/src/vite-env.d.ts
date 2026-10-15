/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_PROXY_TARGET?: string;
  readonly VITE_UCP_API_URL?: string;
  readonly VITE_IDENTITY_API_URL?: string;
  readonly VITE_IDENTITY_UCP_PROJECT_ID?: string;
  readonly VITE_IDENTITY_UCP_WEB_CLIENT_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
