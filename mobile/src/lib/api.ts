import { API_URL } from './config';
import { getToken } from './auth';
import { refreshAccessToken } from './tokenRefresh';

/** Error carrying the HTTP status (0 = network failure) so screens can react. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Endpoints where a 401 is a legitimate response (bad credentials, dead
 *  refresh token) — retrying with a fresh access token would be nonsense. */
function isAuthEndpoint(path: string): boolean {
  return (
    path.startsWith('/api/auth/login') ||
    path.startsWith('/api/auth/refresh') ||
    path.startsWith('/api/auth/logout') ||
    path.startsWith('/api/auth/register')
  );
}

async function doFetch(path: string, options: RequestInit, token: string | null): Promise<Response> {
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(`${API_URL}${path}`, { ...options, headers });
}

/**
 * Thin fetch wrapper: prepends the API base URL, attaches the bearer token,
 * parses JSON, and throws ApiError on non-2xx or network failure.
 *
 * On a 401 (expired access token) we transparently swap the token via
 * `/api/auth/refresh` and retry the request once. Concurrent 401s share the
 * same refresh round-trip via `refreshAccessToken`'s single-flight cache, so
 * the driver stays signed in for as long as the refresh token is valid — no
 * silent kick to the login screen every 30 minutes.
 */
export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = await getToken();

  let resp: Response;
  try {
    resp = await doFetch(path, options, token);
  } catch {
    throw new ApiError(0, 'Network request failed');
  }

  if (resp.status === 401 && !isAuthEndpoint(path)) {
    const fresh = await refreshAccessToken();
    if (fresh) {
      try {
        resp = await doFetch(path, options, fresh);
      } catch {
        throw new ApiError(0, 'Network request failed');
      }
    }
  }

  if (resp.status === 204) return undefined as T;

  const text = await resp.text();
  const data = text ? JSON.parse(text) : null;

  if (!resp.ok) {
    const detail = (data && (data.detail || data.message)) || resp.statusText;
    throw new ApiError(resp.status, typeof detail === 'string' ? detail : 'Request failed');
  }
  return data as T;
}
