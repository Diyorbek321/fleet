import { formatDate, formatDateTime } from '../format';

describe('formatDateTime', () => {
  it('returns an em dash for null input', () => {
    expect(formatDateTime(null)).toBe('—');
  });

  it('returns the original string for an unparseable date', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date');
  });

  it('formats a valid ISO timestamp into a locale string', () => {
    const iso = '2026-06-24T10:30:00.000Z';
    const result = formatDateTime(iso);
    // Locale-specific formatting varies, but a valid date must not pass the
    // raw ISO string through untouched.
    expect(result).not.toBe('—');
    expect(result).not.toBe(iso);
    expect(result.length).toBeGreaterThan(0);
  });
});

describe('formatDate', () => {
  it('returns an em dash for null input', () => {
    expect(formatDate(null)).toBe('—');
  });

  it('returns the original string for an unparseable date', () => {
    expect(formatDate('garbage')).toBe('garbage');
  });

  it('formats a valid ISO date into a locale string', () => {
    const result = formatDate('2026-01-15T00:00:00.000Z');
    expect(result).not.toBe('—');
    expect(result).not.toBe('2026-01-15T00:00:00.000Z');
  });
});
