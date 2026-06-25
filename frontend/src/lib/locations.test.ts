import { describe, it, expect } from 'vitest';
import { statusFromSpeed } from './locations';

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
