import { ApiError, apiFetch } from '../api';

// No token by default; individual tests can override.
jest.mock('../auth', () => ({
  getToken: jest.fn(async () => null),
}));

import { getToken } from '../auth';

const mockGetToken = getToken as jest.MockedFunction<typeof getToken>;

function mockFetchOnce(init: {
  status: number;
  body?: string;
  statusText?: string;
}): void {
  global.fetch = jest.fn(async () => ({
    status: init.status,
    ok: init.status >= 200 && init.status < 300,
    statusText: init.statusText ?? '',
    text: async () => init.body ?? '',
  })) as unknown as typeof fetch;
}

describe('ApiError', () => {
  it('carries the HTTP status and is an Error instance', () => {
    const err = new ApiError(404, 'Not found');
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('ApiError');
    expect(err.status).toBe(404);
    expect(err.message).toBe('Not found');
  });
});

describe('apiFetch', () => {
  beforeEach(() => {
    mockGetToken.mockResolvedValue(null);
    jest.clearAllMocks();
  });

  it('parses and returns the JSON body on a 200 response', async () => {
    mockFetchOnce({ status: 200, body: JSON.stringify({ id: 'abc', value: 42 }) });
    const data = await apiFetch<{ id: string; value: number }>('/api/me/profile');
    expect(data).toEqual({ id: 'abc', value: 42 });
  });

  it('returns undefined for a 204 No Content response', async () => {
    mockFetchOnce({ status: 204 });
    const data = await apiFetch('/api/me/expenses/1', { method: 'DELETE' });
    expect(data).toBeUndefined();
  });

  it('throws ApiError with status 0 when the network request fails', async () => {
    global.fetch = jest.fn(async () => {
      throw new TypeError('connection refused');
    }) as unknown as typeof fetch;

    await expect(apiFetch('/api/me/profile')).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
      message: 'Network request failed',
    });
  });

  it('throws ApiError with the response status and detail on a 4xx error', async () => {
    mockFetchOnce({ status: 401, body: JSON.stringify({ detail: 'Bad credentials' }) });
    await expect(apiFetch('/api/auth/login', { method: 'POST' })).rejects.toMatchObject({
      status: 401,
      message: 'Bad credentials',
    });
  });

  it('falls back to the message field then statusText for the error detail', async () => {
    mockFetchOnce({ status: 500, body: JSON.stringify({ message: 'boom' }) });
    await expect(apiFetch('/api/me/profile')).rejects.toMatchObject({
      status: 500,
      message: 'boom',
    });

    mockFetchOnce({ status: 503, statusText: 'Service Unavailable' });
    await expect(apiFetch('/api/me/profile')).rejects.toMatchObject({
      status: 503,
      message: 'Service Unavailable',
    });
  });

  it('attaches a bearer token when one is stored', async () => {
    mockGetToken.mockResolvedValue('secret-token');
    const fetchMock: jest.Mock = jest.fn(async () => ({
      status: 200,
      ok: true,
      statusText: '',
      text: async () => JSON.stringify({ ok: true }),
    }));
    global.fetch = fetchMock as unknown as typeof fetch;

    await apiFetch('/api/me/profile');

    const requestInit = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = requestInit.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer secret-token');
    expect(headers['Content-Type']).toBe('application/json');
  });
});
