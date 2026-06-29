import type { AuthProviderProps } from "react-oidc-context"

const authority = import.meta.env.VITE_AUTH_AUTHORITY
const clientId = import.meta.env.VITE_AUTH_CLIENT_ID
const redirectUri = import.meta.env.VITE_AUTH_REDIRECT_URI

if (!authority || !clientId || !redirectUri) {
  throw new Error("CRITICAL: Missing required VITE_AUTH environment variables. Check your .env.local file!")
}

import type { User } from "oidc-client-ts"

export const oidcConfig: AuthProviderProps = {
  authority,
  client_id: clientId,
  redirect_uri: redirectUri,
  response_type: "code",
  scope: "openid profile email",
  post_logout_redirect_uri: window.location.origin,
  onSigninCallback: (_user: User | void) => {
    // After successful login, redirect directly to the root
    // The marketing layout will pick this up and redirect to /tenant/dashboard
    // which in turn redirects to /platform/dashboard if they are a platform admin.
    window.location.replace('/')
  }
}
