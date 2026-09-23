import { describe, it, expect, vi, afterEach } from 'vitest';
import * as apiModule from './api';
import { fetchTruckLocationLabels, fetchTruckLocations, statusFromSpeed } from './locations';

afterEach(() => vi.restoreAllMocks());

describe('statusFromSpeed', () => {
  it.each([
    [0, 'stopped'],
    [0.4, 'stopped'],
    [0.5, 'stopped'], // backend "idle" maps to "stopped" in FE vocabulary
    [4.99, 'stopped'],
    [5, 'moving'],
    [15, 'moving'],
    [80, 'moving'],
  ] as const)('speed %f → %s', (speed, expected) => {
    expect(statusFromSpeed(speed)).toBe(expected);
  });
});

describe('fetchTruckLocations', () => {
  it('carries the place name through so the map can show it', async () => {
    vi.spyOn(apiModule, 'api').mockResolvedValueOnce([
      {
        truck_id: 't-1',
        latitude: 41.0167,
        longitude: 70.1436,
        speed: 0,
        heading: null,
        address: "O'zbekiston, Angren",
        recorded_at: '2026-09-16T10:00:00Z',
      },
    ]);

    const byTruck = await fetchTruckLocations();
    expect(byTruck['t-1'].address).toBe("O'zbekiston, Angren");
  });

  it('accepts a position no one has labelled yet', async () => {
    vi.spyOn(apiModule, 'api').mockResolvedValueOnce([
      {
        truck_id: 't-2',
        latitude: 41.0,
        longitude: 70.0,
        speed: 12,
        heading: null,
        address: null,
        recorded_at: '2026-09-16T10:00:00Z',
      },
    ]);

    const byTruck = await fetchTruckLocations();
    expect(byTruck['t-2'].address).toBeNull();
  });
});

describe('fetchTruckLocationLabels', () => {
  it('returns only the trucks that actually have a place name', async () => {
    vi.spyOn(apiModule, 'api').mockResolvedValueOnce([
      { truck_id: 'labelled', latitude: 1, longitude: 2, speed: 0, heading: null, address: 'Qozogʻiston, Sariogʻash', recorded_at: '2026-09-16T10:00:00Z' },
      { truck_id: 'blank', latitude: 3, longitude: 4, speed: 0, heading: null, address: null, recorded_at: '2026-09-16T10:00:00Z' },
      { truck_id: 'empty', latitude: 5, longitude: 6, speed: 0, heading: null, address: '', recorded_at: '2026-09-16T10:00:00Z' },
    ]);

    const labels = await fetchTruckLocationLabels();
    expect(labels).toEqual({ labelled: 'Qozogʻiston, Sariogʻash' });
  });
});
