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

/**
 * The customer a platform operator is currently looking at, if any.
 *
 * sessionStorage, not localStorage: a support session is a thing you are doing
 * right now, and it should not still be open in a tab you reopen next week.
 * Every request made while it is set carries the header, so the backend can
 * refuse the writes and record the reads.
 */
const SUPPORT_ORG_KEY = 'fleet_support_org';

export interface SupportSession {
  orgId: string;
  orgName: string;
}

export const supportSession = {
  get: (): SupportSession | null => {
    try {
      const raw = sessionStorage.getItem(SUPPORT_ORG_KEY);
      return raw ? (JSON.parse(raw) as SupportSession) : null;
    } catch {
      return null;
    }
  },
  set: (session: SupportSession): void => {
    sessionStorage.setItem(SUPPORT_ORG_KEY, JSON.stringify(session));
  },
  clear: (): void => sessionStorage.removeItem(SUPPORT_ORG_KEY),
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

  const buildHeaders = (accessToken: string | null): HeadersInit => {
    // Sent on every request while a support session is open, including the
    // writes the backend will refuse. That refusal is the point: an operator
    // must not be able to change a customer's data by accident, and a header
    // applied selectively by the client would be a rule the client enforces.
    const support = supportSession.get();
    return {
      'Content-Type': 'application/json',
      ...(auth && accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(support ? { 'X-Support-Org': support.orgId } : {}),
      ...(headers as Record<string, string> | undefined),
    };
  };

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

/**
 * Mirrors backend `app.models.enums.UserRole` exactly, in the same order.
 * `superadmin` is the platform operator (us, selling this product); it is not a
 * "bigger admin" — it never sees another company's fleet data, only the
 * `/api/organizations` console.
 */
export type UserRole = 'superadmin' | 'admin' | 'manager' | 'operator' | 'driver';

/**
 * The roles a human may be *assigned* through the UI. `superadmin` is excluded
 * because handing it out from a request body would be privilege escalation into
 * the platform itself; `driver` is excluded because drivers are created through
 * `/api/drivers` so they get a linked Driver profile the mobile app scopes to.
 */
export type AssignableRole = Extract<UserRole, 'admin' | 'manager' | 'operator'>;

export const ASSIGNABLE_ROLES: readonly AssignableRole[] = ['admin', 'manager', 'operator'];

export interface AuthUser {
  id: string;
  org_id: string;
  email: string;
  role: UserRole;
  /**
   * True while this account is on a password an admin chose, and therefore
   * still knows. The app blocks on a change-password prompt until it clears.
   */
  must_change_password: boolean;
}

export const authApi = {
  login: (email: string, password: string) =>
    api<TokenResponse>('/api/auth/login', { method: 'POST', body: { email, password }, auth: false }),
  me: () => api<AuthUser>('/api/auth/me'),
  logout: (refresh_token: string) =>
    api<{ message: string }>('/api/auth/logout', { method: 'POST', body: { refresh_token }, auth: false }),
  /**
   * Changing your own password signs out every *other* session and re-issues
   * this one, so the returned tokens must replace the stored pair — otherwise
   * the caller invalidates itself and is bounced to the login screen for
   * having done the right thing.
   */
  changePassword: (current_password: string, new_password: string) =>
    api<TokenResponse>('/api/auth/change-password', {
      method: 'POST',
      body: { current_password, new_password },
    }),
};

// ---- Organizations (superadmin-only platform console) ----

/**
 * Field names stay snake_case on purpose: unlike the domain modules in
 * `src/lib/*.ts`, this is a thin console over the raw API and an adapter layer
 * would only add a place for the two shapes to drift apart.
 */
export interface Organization {
  id: string;
  name: string;
  is_active: boolean;
  contact_name: string | null;
  contact_phone: string | null;
  notes: string | null;
  created_at: string;
  user_count: number;
  truck_count: number;
  driver_count: number;
  trip_count: number;
}

export interface OrganizationCreate {
  name: string;
  admin_email: string;
  /** Backend enforces min length 8. */
  admin_password: string;
  contact_name?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
}

export interface OrganizationUpdate {
  name?: string;
  /** `false` suspends the company: its users can no longer log in. */
  is_active?: boolean;
  contact_name?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
}

/** A staff user row as returned by both the superadmin and the org-admin endpoints. */
export interface OrgUser {
  id: string;
  org_id: string;
  email: string;
  role: UserRole;
}

export interface OrgUserCreate {
  email: string;
  /** Backend enforces min length 8. */
  password: string;
  role: AssignableRole;
}

export interface OrgUserUpdate {
  role?: AssignableRole;
  password?: string;
}

export const organizationsApi = {
  list: (q?: string) =>
    api<Organization[]>(`/api/organizations${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  get: (orgId: string) => api<Organization>(`/api/organizations/${orgId}`),
  create: (body: OrganizationCreate) =>
    api<Organization>('/api/organizations', { method: 'POST', body }),
  update: (orgId: string, body: OrganizationUpdate) =>
    api<Organization>(`/api/organizations/${orgId}`, { method: 'PATCH', body }),
  /**
   * Destructive and irreversible, so the backend demands the org's exact name as
   * `?confirm=` — the caller must have typed it, a stray click cannot delete a
   * customer.
   */
  remove: (orgId: string, confirm: string) =>
    api<void>(`/api/organizations/${orgId}?confirm=${encodeURIComponent(confirm)}`, {
      method: 'DELETE',
    }),
  listUsers: (orgId: string) => api<OrgUser[]>(`/api/organizations/${orgId}/users`),
  createUser: (orgId: string, body: OrgUserCreate) =>
    api<OrgUser>(`/api/organizations/${orgId}/users`, { method: 'POST', body }),

  /** Totals across every customer. Aggregate only — no one company's data. */
  platformStats: () => api<PlatformStats>('/api/organizations/platform/stats'),

  /** What the operator has done, newest first. Optionally about one customer. */
  auditLog: (orgId?: string) =>
    api<AuditEvent[]>(
      `/api/organizations/platform/audit${orgId ? `?org_id=${orgId}` : ''}`,
    ),
};

export interface PlatformStats {
  organizations: number;
  active_organizations: number;
  suspended_organizations: number;
  users: number;
  drivers: number;
  trucks: number;
  trips: number;
  trips_last_30d: number;
  gps_points: number;
}

export interface AuditEvent {
  id: string;
  actor_email: string;
  action: string;
  target_org_id: string | null;
  target_org_name: string | null;
  detail: string | null;
  created_at: string;
}

// ---- Org-scoped user management (a company's own admin) ----

export const usersApi = {
  list: () => api<OrgUser[]>('/api/auth/users'),
  create: (body: OrgUserCreate) => api<OrgUser>('/api/auth/users', { method: 'POST', body }),
  update: (userId: string, body: OrgUserUpdate) =>
    api<OrgUser>(`/api/auth/users/${userId}`, { method: 'PATCH', body }),
  remove: (userId: string) => api<void>(`/api/auth/users/${userId}`, { method: 'DELETE' }),
};

