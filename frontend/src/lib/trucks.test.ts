import { describe, it, expect } from 'vitest';
import { toFrontendTruck, calculateStats } from './trucks';

const sampleBackend = {
  id: 't-1',
  name: 'Alpha',
  plate_number: 'AA-01',
  model: 'Volvo FH',
  year: 2022,
  status: 'moving' as const,
  fuel_level: 75,
  mileage: 12345,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-04-20T10:30:00Z',
};

describe('toFrontendTruck', () => {
  it('maps snake_case backend shape to camelCase frontend shape', () => {
    const t = toFrontendTruck(sampleBackend);
    expect(t.id).toBe('t-1');
    expect(t.plateNumber).toBe('AA-01');
    expect(t.name).toBe('Alpha');
    expect(t.status).toBe('moving');
    expect(t.lastUpdate).toBeInstanceOf(Date);
  });

  it('defaults lat/lng/speed to 0 when no location is joined', () => {
    const t = toFrontendTruck(sampleBackend);
    expect(t.latitude).toBe(0);
    expect(t.longitude).toBe(0);
    expect(t.speed).toBe(0);
  });

  it('uses joined location when provided', () => {
    const t = toFrontendTruck(sampleBackend, {
      location: {
        truck_id: 't-1',
        latitude: 41.3,
        longitude: 69.2,
        speed: 15,
        heading: 90,
        address: null,
        recorded_at: '2026-04-20T10:29:59Z',
      },
    });
    expect(t.latitude).toBe(41.3);
    expect(t.longitude).toBe(69.2);
    expect(t.speed).toBe(15);
  });

  it('collapses backend "idle" to frontend "stopped"', () => {
    const t = toFrontendTruck({ ...sampleBackend, status: 'idle' });
    expect(t.status).toBe('stopped');
  });

  it('collapses backend "maintenance" to frontend "offline"', () => {
    const t = toFrontendTruck({ ...sampleBackend, status: 'maintenance' });
    expect(t.status).toBe('offline');
  });

  it('sets isEnabled false when status is offline', () => {
    const t = toFrontendTruck({ ...sampleBackend, status: 'offline' });
    expect(t.isEnabled).toBe(false);
  });

  it('pulls driverName from nested driver info', () => {
    const t = toFrontendTruck(sampleBackend, {
      driver: { id: 'd-1', name: 'Aziz K.' },
    });
    expect(t.driverName).toBe('Aziz K.');
  });
});

describe('calculateStats', () => {
  it('counts trucks by status', () => {
    const trucks = [
      toFrontendTruck({ ...sampleBackend, id: '1', status: 'moving' }),
      toFrontendTruck({ ...sampleBackend, id: '2', status: 'moving' }),
      toFrontendTruck({ ...sampleBackend, id: '3', status: 'stopped' }),
      toFrontendTruck({ ...sampleBackend, id: '4', status: 'offline' }),
    ];
    const stats = calculateStats(trucks);
    expect(stats.totalTrucks).toBe(4);
    expect(stats.movingTrucks).toBe(2);
    expect(stats.stoppedTrucks).toBe(1);
    expect(stats.offlineTrucks).toBe(1);
  });

  it('handles empty fleet', () => {
    expect(calculateStats([])).toEqual({
      totalTrucks: 0,
      movingTrucks: 0,
      stoppedTrucks: 0,
      offlineTrucks: 0,
    });
  });
});
