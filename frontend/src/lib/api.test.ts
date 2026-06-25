import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, tokenStorage } from './api';

/** Build a minimal Response-like object usable by fetch mocks. */
function mockResponse(status: number, body: unknown, opts: { text?: boolean } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'mocked',
    json: async () => body,
    text: async () => (opts.text ? String(body) : JSON.stringify(body)),
  } as unknown as Response;
}

describe('tokenStorage', () => {
  afterEach(() => localStorage.clear());

  it('stores, reads, and clears both tokens', () => {
    tokenStorage.set('a', 'r');
    expect(tokenStorage.getAccess()).toBe('a');
    expect(tokenStorage.getRefresh()).toBe('r');
    tokenStorage.clear();
    expect(tokenStorage.getAccess()).toBeNull();
    expect(tokenStorage.getRefresh()).toBeNull();
  });
});

describe('api()', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends Authorization header when a token is stored', async () => {
    tokenStorage.set('access-123', 'refresh-abc');
    fetchMock.mockResolvedValueOnce(mockResponse(200, { hello: 'world' }));

    const result = await api<{ hello: string }>('/api/anything');

    expect(result).toEqual({ hello: 'world' });
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer access-123');
  });

  it('omits Authorization when auth: false', async () => {
    tokenStorage.set('access-123', 'refresh-abc');
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await api('/api/public', { auth: false });

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('serializes body as JSON', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await api('/api/thing', { method: 'POST', body: { a: 1 }, auth: false });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.body).toBe('{"a":1}');
  });

  it('throws ApiError with status and detail on failure', async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(400, { detail: 'Bad input' }));

    await expect(api('/api/thing', { auth: false })).rejects.toMatchObject({
      status: 400,
      detail: 'Bad input',
    });
  });

  it('throws ApiError even when body is not JSON', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => {
        throw new Error('not json');
      },
    } as unknown as Response);

    const err = await api('/api/thing', { auth: false }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
  });

  it('on 401, refreshes token and retries once', async () => {
    tokenStorage.set('stale-access', 'good-refresh');

    fetchMock
      // initial call → 401
      .mockResolvedValueOnce(mockResponse(401, { detail: 'Expired' }))
      // refresh → 200 with new tokens
      .mockResolvedValueOnce(
        mockResponse(200, {
          access_token: 'new-access',
          refresh_token: 'new-refresh',
          token_type: 'bearer',
        }),
      )
      // retried original call → 200
      .mockResolvedValueOnce(mockResponse(200, { ok: true }));

    const result = await api<{ ok: boolean }>('/api/anything');
    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);

    // Retry carries the new access token
    const [, retryInit] = fetchMock.mock.calls[2];
    expect((retryInit.headers as Record<string, string>).Authorization).toBe('Bearer new-access');

    // New tokens persisted
    expect(tokenStorage.getAccess()).toBe('new-access');
    expect(tokenStorage.getRefresh()).toBe('new-refresh');
  });

  it('on 401, if refresh also fails, clears tokens and throws 401', async () => {
    tokenStorage.set('stale', 'bad-refresh');

    fetchMock
      .mockResolvedValueOnce(mockResponse(401, { detail: 'Expired' }))
      .mockResolvedValueOnce(mockResponse(401, { detail: 'Invalid refresh' }));

    await expect(api('/api/anything')).rejects.toMatchObject({ status: 401 });
    expect(tokenStorage.getAccess()).toBeNull();
    expect(tokenStorage.getRefresh()).toBeNull();
  });

  it('does not attempt refresh on 401 when no refresh token is stored', async () => {
    tokenStorage.set('only-access', '');
    // explicitly clear refresh
    localStorage.removeItem('fleet_refresh_token');

    fetchMock.mockResolvedValueOnce(mockResponse(401, { detail: 'nope' }));

    await expect(api('/api/anything')).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1); // no retry
  });

  it('returns undefined for 204 No Content', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: async () => {
        throw new Error('no body');
      },
    } as unknown as Response);

    const result = await api('/api/delete-thing', { method: 'DELETE', auth: false });
    expect(result).toBeUndefined();
  });
});
