import { compareVersions, isOutdated } from '../app-version';

describe('compareVersions', () => {
  it('compares part by part, as numbers', () => {
    expect(compareVersions('0.4.1', '0.5.0')).toBeLessThan(0);
    expect(compareVersions('0.10.0', '0.9.9')).toBeGreaterThan(0);
    expect(compareVersions('1.0', '1.0.0')).toBe(0);
  });
});

describe('isOutdated', () => {
  it('blocks an app older than the minimum', () => {
    expect(isOutdated('0.4.1', '0.5.0')).toBe(true);
  });

  it('lets the minimum itself and newer through', () => {
    expect(isOutdated('0.5.0', '0.5.0')).toBe(false);
    expect(isOutdated('0.6.0', '0.5.0')).toBe(false);
  });

  it('never blocks when the server sets no minimum or the version is unknown', () => {
    expect(isOutdated('0.1.0', '')).toBe(false);
    expect(isOutdated(null, '0.5.0')).toBe(false);
  });
});
