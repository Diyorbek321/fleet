/**
 * Which location samples reach the server.
 *
 * The bug this exists for: a truck standing in a border queue sent nothing,
 * so the server read it as a dead phone and warned the dispatcher. A standing
 * truck must heartbeat; a moving one must still report every real move; and
 * a jittering parked phone must not report every 15 seconds.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import { HEARTBEAT_MS, distanceMeters, sendIfDue, shouldSend } from '../ping-throttle';

const TASHKENT = { latitude: 41.3111, longitude: 69.2797 };

beforeEach(async () => {
  await AsyncStorage.clear();
});

describe('shouldSend', () => {
  it('sends the first sample', () => {
    expect(shouldSend(null, { ...TASHKENT, at: 0 })).toBe(true);
  });

  it('holds back GPS jitter from a parked truck', () => {
    const last = { ...TASHKENT, at: 0 };
    const jitter = { latitude: 41.3112, longitude: 69.2797, at: 15_000 }; // ~11 m
    expect(shouldSend(last, jitter)).toBe(false);
  });

  it('heartbeats a truck that has not moved', () => {
    const last = { ...TASHKENT, at: 0 };
    expect(shouldSend(last, { ...TASHKENT, at: HEARTBEAT_MS })).toBe(true);
  });

  it('reports a real move straight away', () => {
    const last = { ...TASHKENT, at: 0 };
    const moved = { latitude: 41.3121, longitude: 69.2797, at: 15_000 }; // ~111 m
    expect(shouldSend(last, moved)).toBe(true);
  });
});

describe('distanceMeters', () => {
  it('measures a thousandth of a degree of latitude as about 111 m', () => {
    const d = distanceMeters({ ...TASHKENT, at: 0 }, { latitude: 41.3121, longitude: 69.2797 });
    expect(d).toBeGreaterThan(105);
    expect(d).toBeLessThan(117);
  });
});

describe('sendIfDue', () => {
  it('remembers only a sample that was actually sent', async () => {
    const failing = jest.fn(async () => {
      throw new Error('offline');
    });
    await expect(sendIfDue(TASHKENT, failing, 0)).rejects.toThrow('offline');

    // Nothing remembered, so the very next sample is tried again.
    const send = jest.fn(async () => undefined);
    expect(await sendIfDue(TASHKENT, send, 15_000)).toBe(true);
    expect(await sendIfDue(TASHKENT, send, 30_000)).toBe(false);
    expect(send).toHaveBeenCalledTimes(1);
  });
});
