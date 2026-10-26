/**
 * Keeping fixes the phone could not send, and sending them when it can.
 *
 * On the Kazakh steppe a truck can be out of signal for hours. Pings used to
 * be fire-and-forget, so those hours were simply missing: the map drew a
 * straight line from the last fix to the next, and a stop in between never
 * existed. Now a fix that cannot be sent is kept in storage and goes out,
 * oldest first, ahead of the next one that can.
 *
 * Kept in AsyncStorage, not memory: the background task runs in a headless
 * JS context that starts fresh, and the phone may restart in between.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { LocationObject } from 'expo-location';

import { ApiError } from './api';
import { readLastSent, rememberSent, shouldSend } from './ping-throttle';

const QUEUE_KEY = 'fleet_ping_queue';

/** Points per request; the server accepts up to 1000. */
export const BATCH_SIZE = 500;
/** About four days of heartbeats. Past this the oldest go first. */
export const MAX_QUEUED = 1200;

export interface Fix {
  latitude: number;
  longitude: number;
  speed: number;
  heading: number | null;
  /** When the phone took the fix — what places a late point on the timeline. */
  recorded_at: string;
}

export type Delivery = 'sent' | 'queued' | 'skipped';

/** The OS's fix as the server takes it, stamped with when it was taken. */
export function fixFrom(location: LocationObject): Fix {
  return {
    latitude: location.coords.latitude,
    longitude: location.coords.longitude,
    speed: location.coords.speed ?? 0,
    heading: location.coords.heading ?? null,
    recorded_at: new Date(location.timestamp).toISOString(),
  };
}

async function readQueue(): Promise<Fix[]> {
  try {
    const raw = await AsyncStorage.getItem(QUEUE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as Fix[]) : [];
  } catch {
    return [];
  }
}

async function writeQueue(fixes: Fix[]): Promise<void> {
  try {
    if (fixes.length === 0) await AsyncStorage.removeItem(QUEUE_KEY);
    else await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(fixes.slice(-MAX_QUEUED)));
  } catch {
    // Storage full: the fixes are lost, as they were before this existed.
  }
}

export async function queuedCount(): Promise<number> {
  return (await readQueue()).length;
}

/**
 * Worth keeping for later: no network at all, or the server failing. A 4xx
 * is the server answering — no truck assigned, a bad point — and the same
 * points sent again later would be refused again.
 */
function isRetryable(err: unknown): boolean {
  if (!(err instanceof ApiError)) return true;
  return err.status >= 500 || err.status === 429;
}

// The background task and the foreground watch can both fire while the app
// is open; one at a time, or both send the same buffer and one overwrites
// what the other just kept. (A headless context has only the task.)
let inFlight: Promise<unknown> = Promise.resolve();

/**
 * Send ``fix`` and everything kept before it, or keep it for next time.
 *
 * Throttled like a single ping (see ping-throttle.ts). A kept fix counts as
 * sent for throttling, so a phone offline for a day keeps one fix per
 * heartbeat, not one every fifteen seconds.
 */
export function deliverFix(
  fix: Fix,
  sendBatch: (points: Fix[]) => Promise<unknown>,
  now: number = Date.now(),
): Promise<Delivery> {
  const run = inFlight.then(() => deliver(fix, sendBatch, now));
  inFlight = run.catch(() => undefined);
  return run;
}

async function deliver(
  fix: Fix,
  sendBatch: (points: Fix[]) => Promise<unknown>,
  now: number,
): Promise<Delivery> {
  const sample = { latitude: fix.latitude, longitude: fix.longitude, at: now };
  if (!shouldSend(await readLastSent(), sample)) return 'skipped';

  let pending = [...(await readQueue()), fix];
  try {
    while (pending.length > 0) {
      await sendBatch(pending.slice(0, BATCH_SIZE));
      pending = pending.slice(BATCH_SIZE);
      // Saved after every accepted batch, so a drop mid-flush does not send
      // the accepted ones again (the server also ignores repeats).
      if (pending.length > 0) await writeQueue(pending);
    }
  } catch (err) {
    if (isRetryable(err)) {
      await writeQueue(pending);
      await rememberSent(sample);
      return 'queued';
    }
    // A dead session: keep everything for after the driver signs back in.
    // Any other refusal would refuse these points forever and block every
    // later fix behind them, so they are dropped.
    if (!(err instanceof ApiError && err.status === 401)) await writeQueue([]);
    throw err;
  }
  await writeQueue([]);
  await rememberSent(sample);
  return 'sent';
}

/** Forget kept fixes — on sign-out they belong to someone else's truck. */
export async function clearPingQueue(): Promise<void> {
  await AsyncStorage.removeItem(QUEUE_KEY).catch(() => {});
}
