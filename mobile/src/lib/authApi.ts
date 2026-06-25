import { apiFetch } from './api';
import { clearTokens, getRefreshToken, setRefreshToken, setToken } from './auth';
import { stopBackgroundTracking } from './location-task';

interface TokenOut {
  access_token: string;
  refresh_token: string;
}

/** Authenticate against the backend and persist the tokens. */
export async function signIn(email: string, password: string): Promise<void> {
  const res = await apiFetch<TokenOut>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  await setToken(res.access_token);
  await setRefreshToken(res.refresh_token);
}

/** Revoke the refresh token server-side (best effort) and clear local tokens. */
export async function signOut(): Promise<void> {
  // Make sure no background location service keeps running after sign out.
  try {
    await stopBackgroundTracking();
  } catch {
    // Non-fatal: continue clearing the session regardless.
  }

  const refresh = await getRefreshToken();
  if (refresh) {
    try {
      await apiFetch('/api/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh_token: refresh }),
      });
    } catch {
      // Ignore server errors on logout — we clear locally regardless.
    }
  }
  await clearTokens();
}
