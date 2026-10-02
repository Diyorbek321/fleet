import { describe, it, expect } from 'vitest';
import type { Truck } from '@/types';
import { daysLeft, insuranceState, nearestDaysLeft, summarize, localToday } from './insurance';

const TODAY = '2026-10-02';

function truck(overrides: Partial<Truck> = {}): Truck {
  return {
    id: 't',
    plateNumber: '01A123BC',
    name: '01A123BC',
    status: 'stopped',
    speed: 0,
    latitude: 0,
    longitude: 0,
    lastUpdate: new Date(),
    isEnabled: true,
    ...overrides,
  };
}

describe('daysLeft', () => {
  it('counts calendar days, negative once lapsed', () => {
    expect(daysLeft('2026-10-02', TODAY)).toBe(0);
    expect(daysLeft('2026-10-09', TODAY)).toBe(7);
    expect(daysLeft('2026-09-30', TODAY)).toBe(-2);
    expect(daysLeft('2027-10-02', TODAY)).toBe(365);
  });
});

describe('insuranceState', () => {
  it('buckets by distance to the date', () => {
    expect(insuranceState(null, TODAY)).toBe('missing');
    expect(insuranceState('2026-10-01', TODAY)).toBe('expired');
    expect(insuranceState('2026-10-02', TODAY)).toBe('urgent');
    expect(insuranceState('2026-10-09', TODAY)).toBe('urgent');
    expect(insuranceState('2026-10-10', TODAY)).toBe('soon');
    expect(insuranceState('2026-11-01', TODAY)).toBe('soon');
    expect(insuranceState('2026-11-02', TODAY)).toBe('ok');
  });
});

describe('nearestDaysLeft', () => {
  it('is the soonest policy across all three countries', () => {
    const t = truck({
      insuranceExpiry: '2027-01-01',
      insuranceExpiryKz: '2026-10-05',
      insuranceExpiryRf: null,
    });
    expect(nearestDaysLeft(t, TODAY)).toBe(3);
    expect(nearestDaysLeft(truck(), TODAY)).toBeNull();
  });
});

describe('summarize', () => {
  it('counts policies, not trucks', () => {
    const s = summarize(
      [
        truck({ insuranceExpiry: '2026-09-01', insuranceExpiryKz: '2026-09-15', insuranceExpiryRf: '2026-10-20' }),
        truck({ insuranceExpiry: '2027-06-01' }),
      ],
      TODAY,
    );
    expect(s).toEqual({ expired: 2, soon: 1, missing: 2 });
  });
});

describe('localToday', () => {
  it('formats the local calendar date', () => {
    expect(localToday(new Date(2026, 0, 5, 23, 30))).toBe('2026-01-05');
  });
});
