import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { devicesApi } from './devices';
import { tokenStorage } from './api';

function mockResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'mocked',
    json: async () => body,
  } as unknown as Response;
}

describe('devicesApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    tokenStorage.set('admin-access', 'admin-refresh');
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it('list() adapts snake_case and parses dates', async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, [
        {
          id: 'd-1',
          imei: '352094081234567',
          name: 'Teltonika',
          truck_id: 't-1',
          last_seen_at: '2026-04-20T10:00:00Z',
          created_at: '2026-04-01T00:00:00Z',
        },
      ]),
    );

    const devices = await devicesApi.list();
    expect(devices).toHaveLength(1);
    expect(devices[0].imei).toBe('352094081234567');
    expect(devices[0].truckId).toBe('t-1');
    expect(devices[0].lastSeenAt).toBeInstanceOf(Date);
    expect(devices[0].createdAt).toBeInstanceOf(Date);
  });

  it('list() handles null last_seen_at', async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, [
        {
          id: 'd-1',
          imei: 'x',
          name: null,
          truck_id: null,
          last_seen_at: null,
          created_at: '2026-04-01T00:00:00Z',
        },
      ]),
    );
    const [device] = await devicesApi.list();
    expect(device.lastSeenAt).toBeNull();
    expect(device.truckId).toBeNull();
  });

  it('enroll() sends camelCase → snake_case and surfaces api_key once', async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(201, {
        id: 'd-1',
        imei: '111',
        name: 'n',
        truck_id: 't-1',
        last_seen_at: null,
        created_at: '2026-04-01T00:00:00Z',
        api_key: 'secret-key-xyz',
      }),
    );

    const created = await devicesApi.enroll({
      imei: '111',
      name: 'n',
      truckId: 't-1',
    });

    expect(created.apiKey).toBe('secret-key-xyz');
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ imei: '111', name: 'n', truck_id: 't-1' });
  });
});
