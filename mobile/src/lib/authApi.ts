import { apiFetch } from './api';
import { clearTokens, getRefreshToken, setRefreshToken, setToken } from './auth';
import { stopBackgroundTracking } from './location-task';
import { refreshAccessToken } from './tokenRefresh';

interface TokenOut {
  access_token: string;
  refresh_token: string;
}

/** Re-exported so existing callers of `authApi.refreshAccessToken` keep
 *  working — the implementation now lives in `./tokenRefresh` to break the
 *  `api.ts` <-> `authApi.ts` circular dependency. */
export { refreshAccessToken };

/** Authenticate against the backend and persist the tokens. */
export async function signIn(email: string, password: string): Promise<void> {
  const res = await apiFetch<TokenOut>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  await setToken(res.access_token);
  await setRefreshToken(res.refresh_token);
}

export interface Account {
  id: string;
  email: string;
  role: string;
  /** True while this account is on a password the dispatcher chose. */
  must_change_password: boolean;
}

/** The signed-in account itself, as opposed to the Driver profile behind it. */
export async function fetchAccount(): Promise<Account> {
  return apiFetch<Account>('/api/auth/me');
}

/**
 * Change the signed-in driver's own password.
 *
 * Driver logins are created by a dispatcher with a password the dispatcher
 * picked, so until this existed every driver account was on a password someone
 * else knew and the driver could not do anything about it.
 *
 * The server invalidates every token minted under the old password — including
 * the one that authorised this very call — and returns a replacement pair, so
 * the new tokens must be stored or the driver is signed out for having changed
 * their password. Other devices stay signed out, which is the point.
 */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await apiFetch<TokenOut>('/api/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
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
