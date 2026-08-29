import { describe, it, expect } from 'vitest';

import { formatAmount, formatKm, formatL100km, formatLiters, toL100km } from './format';

describe('toL100km', () => {
  it('converts km-per-litre into litres-per-100km', () => {
    // 2.86 km/L is roughly the demo fleet's 35 L/100km baseline.
    expect(toL100km(2.86)).toBeCloseTo(34.97, 2);
    expect(toL100km(4)).toBe(25);
  });

  it('returns null when efficiency is missing or nonsensical', () => {
    expect(toL100km(0)).toBeNull();
    expect(toL100km(-1)).toBeNull();
    expect(toL100km(Number.NaN)).toBeNull();
    expect(toL100km(Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe('formatL100km', () => {
  it('renders one decimal place', () => {
    expect(formatL100km(4)).toBe('25.0');
  });

  it('renders an em dash when there is nothing to show', () => {
    expect(formatL100km(0)).toBe('—');
  });
});

describe('formatAmount', () => {
  it('groups thousands without a currency symbol', () => {
    expect(formatAmount(198389054)).toBe('198,389,054');
  });

  it('honours a fixed number of decimals', () => {
    expect(formatAmount(14106.06, 2)).toBe('14,106.06');
  });

  it('rounds to whole units by default', () => {
    expect(formatAmount(14106.6)).toBe('14,107');
  });

  it('guards against non-finite input', () => {
    expect(formatAmount(Number.NaN)).toBe('—');
  });
});

describe('formatLiters / formatKm', () => {
  it('formats volumes and distances with grouping', () => {
    expect(formatLiters(14064)).toBe('14,064');
    expect(formatLiters(1170.2, 1)).toBe('1,170.2');
    expect(formatKm(43496.1, 1)).toBe('43,496.1');
  });

  it('guards against non-finite input', () => {
    expect(formatLiters(Number.NaN)).toBe('—');
    expect(formatKm(Number.NaN)).toBe('—');
  });
});
