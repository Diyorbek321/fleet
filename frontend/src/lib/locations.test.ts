import { describe, it, expect, vi, afterEach } from 'vitest';
import * as apiModule from './api';
import {
  LIVE_FOR_MS,
  fetchTruckLocationLabels,
  fetchTruckLocations,
  liveStatus,
  statusFromSpeed,
} from './locations';

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

// A position is a fact about a moment. Coloured by its speed alone, a truck
// silent for three days stayed green "moving" on the map — the one lie a
// dispatcher cannot catch by looking.
describe('liveStatus', () => {
  const NOW = new Date('2026-10-26T12:00:00Z');
  const ago = (ms: number) => new Date(NOW.getTime() - ms);

  it('follows the speed while the fix is fresh', () => {
    expect(liveStatus(60, ago(60_000), NOW)).toBe('moving');
    expect(liveStatus(0, ago(60_000), NOW)).toBe('stopped');
  });

  it('turns offline once the fix is older than the live window', () => {
    expect(liveStatus(60, ago(LIVE_FOR_MS + 1), NOW)).toBe('offline');
    expect(liveStatus(60, ago(3 * 24 * 3600_000), NOW)).toBe('offline');
  });
});
