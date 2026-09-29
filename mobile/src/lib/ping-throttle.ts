/**
 * Which location samples are worth sending.
 *
 * The OS used to be asked for a fix only after 50 m of movement, so a truck
 * parked for two days in a border queue sent nothing — and the server, which
 * cannot tell a parked truck from a dead phone, showed it offline and warned
 * the dispatcher its GPS was gone. Now the OS samples on time alone, and this
 * decides what reaches the server: every real move, plus one heartbeat every
 * few minutes while standing still.
 *
 * The last sent sample lives in AsyncStorage, not memory: the background task
 * runs in a headless JS context that starts fresh.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

const LAST_SENT_KEY = 'fleet_last_location_sent';

/** Movement that counts as the truck having gone somewhere. */
export const MIN_MOVE_METERS = 50;
/** How often a standing truck says "still here". */
export const HEARTBEAT_MS = 5 * 60_000;

export interface SentSample {
  latitude: number;
  longitude: number;
  at: number;
}

/** Great-circle distance, in metres. */
export function distanceMeters(a: SentSample, b: Omit<SentSample, 'at'>): number {
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = rad(b.latitude - a.latitude);
  const dLng = rad(b.longitude - a.longitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.latitude)) * Math.cos(rad(b.latitude)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h));
}

/** Pure decision, so it can be tested without storage or a clock. */
export function shouldSend(last: SentSample | null, next: SentSample): boolean {
  if (!last) return true;
  if (next.at - last.at >= HEARTBEAT_MS) return true;
  return distanceMeters(last, next) >= MIN_MOVE_METERS;
}

async function readLast(): Promise<SentSample | null> {
  try {
    const raw = await AsyncStorage.getItem(LAST_SENT_KEY);
    return raw ? (JSON.parse(raw) as SentSample) : null;
  } catch {
    return null;
  }
}

/**
 * Send ``sample`` through ``send`` if it is worth sending, and remember it.
 *
 * Only a successful send is remembered: a failed one leaves the old sample in
 * place, so the next fix is tried again instead of waiting out a heartbeat.
 */
export async function sendIfDue(
  sample: Omit<SentSample, 'at'>,
  send: () => Promise<unknown>,
  now: number = Date.now(),
): Promise<boolean> {
  const next = { ...sample, at: now };
  if (!shouldSend(await readLast(), next)) return false;
  await send();
  try {
    await AsyncStorage.setItem(LAST_SENT_KEY, JSON.stringify(next));
  } catch {
    // Storage full or unavailable: the worst case is one extra ping.
  }
  return true;
}

/** Forget the last sample, so the first fix after sign-in always goes out. */
export async function resetPingThrottle(): Promise<void> {
  await AsyncStorage.removeItem(LAST_SENT_KEY).catch(() => {});
}
