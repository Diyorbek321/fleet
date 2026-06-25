const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

const ACCESS_KEY = 'fleet_access_token';
const REFRESH_KEY = 'fleet_refresh_token';

export const tokenStorage = {
  getAccess: (): string | null => localStorage.getItem(ACCESS_KEY),
  getRefresh: (): string | null => localStorage.getItem(REFRESH_KEY),
  set: (access: string, refresh: string): void => {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear: (): void => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

let refreshPromise: Promise<TokenResponse> | null = null;

async function refreshTokens(): Promise<TokenResponse> {
  const refresh = tokenStorage.getRefresh();
  if (!refresh) throw new ApiError(401, 'No refresh token');

  const res = await fetch(`${BASE_URL}/api/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!res.ok) {
    tokenStorage.clear();
    throw new ApiError(res.status, 'Session expired');
  }
  const data = (await res.json()) as TokenResponse;
  tokenStorage.set(data.access_token, data.refresh_token);
  return data;
}

export interface ApiOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  auth?: boolean;
}

export async function api<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { body, auth = true, headers, ...rest } = opts;

  const buildHeaders = (accessToken: string | null): HeadersInit => ({
    'Content-Type': 'application/json',
    ...(auth && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    ...(headers as Record<string, string> | undefined),
  });

  const doFetch = (accessToken: string | null): Promise<Response> =>
    fetch(`${BASE_URL}${path}`, {
      ...rest,
      headers: buildHeaders(accessToken),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

  let res = await doFetch(tokenStorage.getAccess());

  if (res.status === 401 && auth && tokenStorage.getRefresh()) {
    try {
      refreshPromise ??= refreshTokens().finally(() => {
        refreshPromise = null;
      });
      const { access_token } = await refreshPromise;
      res = await doFetch(access_token);
    } catch {
      tokenStorage.clear();
      throw new ApiError(401, 'Session expired');
    }
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const err = await res.json();
      detail = err.detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- Auth endpoints ----

export interface AuthUser {
  id: string;
  email: string;
  role: 'admin' | 'operator' | 'viewer';
}

export const authApi = {
  login: (email: string, password: string) =>
    api<TokenResponse>('/api/auth/login', { method: 'POST', body: { email, password }, auth: false }),
  me: () => api<AuthUser>('/api/auth/me'),
  logout: (refresh_token: string) =>
    api<{ message: string }>('/api/auth/logout', { method: 'POST', body: { refresh_token }, auth: false }),
};
