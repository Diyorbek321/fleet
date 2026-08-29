/**
 * The snake_case → camelCase adapter for the leakage endpoints.
 *
 * A field missed here does not throw: it lands as `undefined`, the page's
 * `?? 0` fallback turns it into a confident zero, and the dashboard reports
 * that nothing leaked. Silent understatement is the worst possible failure for
 * this feature, so every field is asserted explicitly.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({ api: vi.fn() }));

const { api } = await import('./api');
const { analyticsApi } = await import('./analytics');

const apiMock = vi.mocked(api);

beforeEach(() => {
  apiMock.mockReset();
});

describe('leakageSummary', () => {
  const backend = {
    window_days: 45,
    estimated_fuel_waste_cost: 12_450_000,
    flagged_trucks: 2,
    fuel_baseline_l_per_100km: 34.5,
    unauthorized_stop_count: 3,
    total_idle_hours: 41.5,
    active_trips: 7,
    delivered_trips: 12,
  };

  it('maps every field', async () => {
    apiMock.mockResolvedValue(backend);

    await expect(analyticsApi.leakageSummary(30)).resolves.toEqual({
      windowDays: 45,
      estimatedFuelWasteCost: 12_450_000,
      flaggedTrucks: 2,
      fuelBaselineLPer100km: 34.5,
      unauthorizedStopCount: 3,
      totalIdleHours: 41.5,
      activeTrips: 7,
      deliveredTrips: 12,
    });
  });

  it('keeps the window the server actually measured, not the one requested', async () => {
    // The backend clamps the window to the GPS retention period. Echoing back
    // the requested 365 would label a 45-day figure as a year's worth.
    apiMock.mockResolvedValue(backend);

    const summary = await analyticsApi.leakageSummary(365);
    expect(summary.windowDays).toBe(45);
  });

  it('requests the window it was given', async () => {
    apiMock.mockResolvedValue(backend);

    await analyticsApi.leakageSummary(7);
    expect(apiMock).toHaveBeenCalledWith('/api/analytics/leakage-summary?days=7');
  });

  it('defaults to a 30-day window', async () => {
    apiMock.mockResolvedValue(backend);

    await analyticsApi.leakageSummary();
    expect(apiMock).toHaveBeenCalledWith('/api/analytics/leakage-summary?days=30');
  });
});

describe('fuelAnomalies', () => {
  it('maps every field of every truck row', async () => {
    apiMock.mockResolvedValue({
      window_days: 30,
      trucks: [
        {
          truck_id: 'truck-1',
          truck_name: 'Volvo FH',
          plate_number: '01A123BC',
          distance_km: 2400,
          liters: 1180,
          l_per_100km: 49.2,
          baseline_l_per_100km: 34.5,
          flagged: true,
          estimated_waste_cost: 8_200_000,
        },
      ],
    });

    await expect(analyticsApi.fuelAnomalies(30)).resolves.toEqual([
      {
        truckId: 'truck-1',
        truckName: 'Volvo FH',
        plateNumber: '01A123BC',
        distanceKm: 2400,
        liters: 1180,
        lPer100km: 49.2,
        baselineLPer100km: 34.5,
        flagged: true,
        estimatedWasteCost: 8_200_000,
      },
    ]);
  });

  it('returns an empty list when no truck qualified', async () => {
    apiMock.mockResolvedValue({ window_days: 30, trucks: [] });
    await expect(analyticsApi.fuelAnomalies()).resolves.toEqual([]);
  });
});

describe('unauthorizedStops', () => {
  it('maps every field of every stop', async () => {
    apiMock.mockResolvedValue({
      window_days: 30,
      stops: [
        {
          truck_id: 'truck-1',
          truck_name: 'Volvo FH',
          plate_number: '01A123BC',
          latitude: 41.311081,
          longitude: 69.240562,
          started_at: '2026-08-10T09:00:00Z',
          ended_at: '2026-08-10T11:30:00Z',
          duration_minutes: 150.4,
        },
      ],
    });

    await expect(analyticsApi.unauthorizedStops(30)).resolves.toEqual([
      {
        truckId: 'truck-1',
        truckName: 'Volvo FH',
        plateNumber: '01A123BC',
        latitude: 41.311081,
        longitude: 69.240562,
        startedAt: '2026-08-10T09:00:00Z',
        endedAt: '2026-08-10T11:30:00Z',
        durationMinutes: 150.4,
      },
    ]);
  });
});
