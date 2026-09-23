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

/**
 * How long a request may hang before it is treated as a failure.
 *
 * Without this a dead link — a lorry in a Kazakh dead zone, a proxy that
 * accepted the connection and then stopped answering — leaves `fetch` pending
 * forever, and a screen that shows a spinner until its load resolves shows that
 * spinner until the app is killed. A driver reads that as "the section is
 * broken", which is exactly what it is. Generous, because uploads on 2G are
 * slow, but finite.
 */
const REQUEST_TIMEOUT_MS = 30_000;

async function doFetch(path: string, options: RequestInit, token: string | null): Promise<Response> {
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers: Record<string, string> = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  // Our controller always wins the timeout; a caller-supplied signal is
  // chained onto it rather than replacing it, so passing one cannot quietly
  // hand a request back its unlimited wait.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const abortFromCaller = () => controller.abort();
  options.signal?.addEventListener('abort', abortFromCaller);
  try {
    return await fetch(`${API_URL}${path}`, { ...options, headers, signal: controller.signal });
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abortFromCaller);
  }
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
  // A gateway timeout or a crashed worker answers with HTML, not JSON. Letting
  // JSON.parse throw here produced a SyntaxError, which is not an ApiError, so
  // screens fell through their error branch and showed nothing — a failure that
  // looked like a blank screen instead of like a failure.
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    if (resp.ok) throw new ApiError(resp.status, 'Malformed response');
  }

  if (!resp.ok) {
    // `||`, not `??`: an empty statusText is the common case on a proxy error,
    // and it would otherwise become an error with no message — which is how a
    // failure ends up showing as a blank alert.
    throw new ApiError(resp.status, errorDetail(data) || resp.statusText || `HTTP ${resp.status}`);
  }
  return data as T;
}

/** FastAPI puts the human-readable reason in `detail`; some proxies use `message`. */
function errorDetail(data: unknown): string | null {
  if (typeof data !== 'object' || data === null) return null;
  const body = data as { detail?: unknown; message?: unknown };
  const detail = body.detail ?? body.message;
  return typeof detail === 'string' && detail ? detail : null;
}
