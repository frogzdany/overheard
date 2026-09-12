// Runtime configuration for the web dashboard.
//
// Everything comes from build-time `NEXT_PUBLIC_*` env vars: there is no
// server-side `/config` endpoint in this build. `appConfig()` is the single
// synchronous read used by `auth.ts`; when the Auth0 values are empty the app
// runs without a login gate (see AuthGate).

export interface RuntimeConfig {
  auth0Domain: string
  auth0ClientId: string
  auth0Audience: string
}

const CONFIG: RuntimeConfig = {
  auth0Domain: process.env.NEXT_PUBLIC_AUTH0_DOMAIN ?? "",
  auth0ClientId: process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID ?? "",
  auth0Audience: process.env.NEXT_PUBLIC_AUTH0_AUDIENCE ?? "",
}

/** Synchronous config read: the baked `NEXT_PUBLIC_AUTH0_*` env vars. */
export function appConfig(): RuntimeConfig {
  return CONFIG
}
