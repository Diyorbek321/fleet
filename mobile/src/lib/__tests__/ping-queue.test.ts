/**
 * Fixes taken with no network are kept and sent when it comes back, so the
 * track across a dead zone is a line of real points, not a straight jump.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import { ApiError } from '../api';
import { HEARTBEAT_MS } from '../ping-throttle';
import { BATCH_SIZE, MAX_QUEUED, deliverFix, queuedCount, type Fix } from '../ping-queue';

let clock = 0;
function fix(lat: number): Fix {
  clock += HEARTBEAT_MS; // every fix is due, so throttling never hides one
  return { latitude: lat, longitude: 69, speed: 0, heading: null, recorded_at: new Date(clock).toISOString() };
}

const offline = async () => {
  throw new TypeError('Network request failed');
};

beforeEach(async () => {
  clock = 0;
  await AsyncStorage.clear();
});

describe('deliverFix', () => {
  it('keeps fixes while offline and sends them all, oldest first, once back', async () => {
    for (const lat of [41, 42, 43]) {
      const f = fix(lat);
      expect(await deliverFix(f, offline, Date.parse(f.recorded_at))).toBe('queued');
    }
    expect(await queuedCount()).toBe(3);

    const batches: Fix[][] = [];
    const f = fix(44);
    expect(await deliverFix(f, async (points) => void batches.push(points), Date.parse(f.recorded_at))).toBe('sent');

    expect(batches.flat().map((p) => p.latitude)).toEqual([41, 42, 43, 44]);
    expect(await queuedCount()).toBe(0);
  });

  it('treats a server error like no network', async () => {
    const f = fix(41);
    const down = async () => {
      throw new ApiError(502, 'Bad gateway');
    };
    expect(await deliverFix(f, down, Date.parse(f.recorded_at))).toBe('queued');
  });

  it('does not keep fixes the server refused on purpose', async () => {
    // 409: no truck assigned. Retrying the same points later changes nothing.
    const f = fix(41);
    const refused = async () => {
      throw new ApiError(409, 'no truck');
    };
    await expect(deliverFix(f, refused, Date.parse(f.recorded_at))).rejects.toThrow('no truck');
    expect(await queuedCount()).toBe(0);
  });

  it('sends a long buffer in requests the server accepts', async () => {
    for (let i = 0; i < BATCH_SIZE + 10; i++) {
      const f = fix(41 + i / 1000);
      await deliverFix(f, offline, Date.parse(f.recorded_at));
    }
    const sizes: number[] = [];
    const f = fix(50);
    await deliverFix(f, async (points) => void sizes.push(points.length), Date.parse(f.recorded_at));
    expect(sizes.every((n) => n <= BATCH_SIZE)).toBe(true);
    expect(sizes.reduce((a, b) => a + b, 0)).toBe(BATCH_SIZE + 11);
  });

  it('keeps what was not sent when the network drops mid-flush', async () => {
    for (let i = 0; i < BATCH_SIZE + 5; i++) {
      const f = fix(41);
      await deliverFix(f, offline, Date.parse(f.recorded_at));
    }
    let calls = 0;
    const flaky = async () => {
      calls += 1;
      if (calls > 1) throw new TypeError('Network request failed');
    };
    const f = fix(42);
    expect(await deliverFix(f, flaky, Date.parse(f.recorded_at))).toBe('queued');
    expect(await queuedCount()).toBe(6); // 5 left over + the new fix
  });

  it('drops the oldest fixes past the cap rather than filling the phone', async () => {
    const many = Array.from({ length: MAX_QUEUED + 5 }, (_, i) => fix(41 + i / 100000));
    await AsyncStorage.setItem('fleet_ping_queue', JSON.stringify(many.slice(0, MAX_QUEUED)));
    const f = many[MAX_QUEUED];
    await deliverFix(f, offline, Date.parse(f.recorded_at));
    expect(await queuedCount()).toBe(MAX_QUEUED);
  });

  it('does not let one refused point block every later fix', async () => {
    const old = fix(41);
    await deliverFix(old, offline, Date.parse(old.recorded_at));
    const f = fix(42);
    const invalid = async () => {
      throw new ApiError(422, 'bad point');
    };
    await expect(deliverFix(f, invalid, Date.parse(f.recorded_at))).rejects.toThrow('bad point');
    expect(await queuedCount()).toBe(0);
  });

  it('keeps the buffer through a dead session, for after sign-in', async () => {
    const old = fix(41);
    await deliverFix(old, offline, Date.parse(old.recorded_at));
    const f = fix(42);
    const expired = async () => {
      throw new ApiError(401, 'expired');
    };
    await expect(deliverFix(f, expired, Date.parse(f.recorded_at))).rejects.toThrow('expired');
    expect(await queuedCount()).toBe(1);
  });

  it('runs one delivery at a time, so a buffer is never sent twice', async () => {
    const queued = fix(41);
    await deliverFix(queued, offline, Date.parse(queued.recorded_at));
    const sent: number[] = [];
    const slow = async (points: Fix[]) => {
      await new Promise((r) => setTimeout(r, 10));
      sent.push(...points.map((p) => p.latitude));
    };
    const a = fix(42);
    const b = fix(43);
    await Promise.all([
      deliverFix(a, slow, Date.parse(a.recorded_at)),
      deliverFix(b, slow, Date.parse(b.recorded_at)),
    ]);
    expect(sent).toEqual([41, 42, 43]);
  });
});
