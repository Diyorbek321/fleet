import { API_URL } from './config';
import { getRefreshToken, setRefreshToken, setToken } from './auth';

interface TokenOut {
  access_token: string;
  refresh_token: string;
}

/**
 * Exchange the stored refresh token for a fresh access + refresh pair.
 *
 * Lives in its own module (rather than `authApi.ts`) so that `api.ts` can
 * import it with a normal top-level `import` instead of a lazy `require`:
 * `api.ts` needs this function to recover from a 401, and `authApi.ts` needs
 * `apiFetch` from `api.ts` for `signIn`/`signOut` — importing this file from
 * both sides avoids that cycle since it has no dependency back on `api.ts`.
 *
 * Uses raw `fetch` (not `apiFetch`) to avoid recursion — `apiFetch` calls this
 * on 401. All in-flight refreshes share the same promise so a burst of expired
 * requests only triggers one round-trip (and one refresh-token rotation).
 *
 * Returns the new access token on success, or `null` if the refresh token is
 * missing / rejected. On `null` the caller should treat the session as dead
 * (the tokens are left in storage so the user is not silently logged out —
 * they can re-login manually).
 */
let refreshInFlight: Promise<string | null> | null = null;

export function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const refresh = await getRefreshToken();
      if (!refresh) return null;
      const resp = await fetch(`${API_URL}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!resp.ok) return null;
      const data = (await resp.json()) as TokenOut;
      await setToken(data.access_token);
      await setRefreshToken(data.refresh_token);
      return data.access_token;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}
