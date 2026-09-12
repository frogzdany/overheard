// Auth0 SPA login for the web dashboard. Gives the browser app a real Auth0
// access token. The Auth0 settings come from `appConfig()` (the
// `NEXT_PUBLIC_AUTH0_*` env vars); when they're absent the dashboard runs
// without a sign-in gate (see AuthGate).

import type { Auth0Client } from "@auth0/auth0-spa-js"
import { appConfig } from "./runtimeConfig"

const SCOPE = "openid profile email offline_access"

export function auth0Configured(): boolean {
  const c = appConfig()
  return Boolean(c.auth0Domain && c.auth0ClientId && c.auth0Audience)
}

// Last access token fetched by initAuth(); accountToken() reads this synchronously.
let _cachedToken: string | null = null
export function cachedAccountToken(): string | null {
  return _cachedToken
}

let _clientPromise: Promise<Auth0Client> | null = null
function client(): Promise<Auth0Client> {
  if (!_clientPromise) {
    // Dynamic import keeps the SDK (and its window usage) out of the static
    // build's prerender pass.
    _clientPromise = (async () => {
      const c = appConfig()
      const { createAuth0Client } = await import("@auth0/auth0-spa-js")
      return createAuth0Client({
        domain: c.auth0Domain,
        clientId: c.auth0ClientId,
        useRefreshTokens: true,
        cacheLocation: "localstorage",
        authorizationParams: {
          redirect_uri: window.location.origin,
          audience: c.auth0Audience,
          scope: SCOPE,
        },
      })
    })()
  }
  return _clientPromise
}

/** Initialize: finish a redirect login if present, then cache an access token.
 * Returns whether the user is authenticated. */
export async function initAuth(): Promise<boolean> {
  if (!auth0Configured() || typeof window === "undefined") return false
  const a = await client()

  const q = new URLSearchParams(window.location.search)
  if ((q.has("code") || q.has("error")) && q.has("state")) {
    try {
      await a.handleRedirectCallback()
    } catch {
      // ignore a stale/duplicate callback
    }
    window.history.replaceState({}, document.title, window.location.pathname)
  }

  if (await a.isAuthenticated()) {
    try {
      _cachedToken = await a.getTokenSilently({
        authorizationParams: { audience: appConfig().auth0Audience },
      })
      return true
    } catch {
      return false
    }
  }
  return false
}

/** Return a current access token, refreshing it via the refresh token when the
 * cached one is stale (`getTokenSilently` reuses the cache and only hits Auth0
 * when needed). Also refreshes the synchronous `cachedAccountToken()` snapshot.
 * Returns null when not configured or not signed in. */
export async function freshAccountToken(): Promise<string | null> {
  if (!auth0Configured() || typeof window === "undefined") return null
  try {
    const a = await client()
    _cachedToken = await a.getTokenSilently({
      authorizationParams: { audience: appConfig().auth0Audience },
    })
    return _cachedToken
  } catch {
    return null
  }
}

/** Auth0 `sub` of the signed-in user ("auth0|abc123"), used to stamp who
 * approved a suggested action. Null when Auth0 isn't configured or nobody is
 * signed in — callers fall back to a local identity. */
export async function accountSub(): Promise<string | null> {
  if (!auth0Configured() || typeof window === "undefined") return null
  try {
    const a = await client()
    const user = await a.getUser()
    return user?.sub ?? null
  } catch {
    return null
  }
}

export async function signIn(): Promise<void> {
  const a = await client()
  await a.loginWithRedirect({
    authorizationParams: {
      redirect_uri: window.location.origin,
      audience: appConfig().auth0Audience,
      scope: SCOPE,
    },
  })
}

export async function signOut(): Promise<void> {
  _cachedToken = null
  const a = await client()
  await a.logout({ logoutParams: { returnTo: window.location.origin } })
}
