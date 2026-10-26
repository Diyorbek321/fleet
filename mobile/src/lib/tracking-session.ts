/**
 * "The server refused this session" — remembered across JS contexts.
 *
 * The background task stops tracking on a 401 its token refresh could not
 * fix. The screen restarts stopped tracking on every open, so without this it
 * would restart straight into the same 401 — and the task would post another
 * "sign in again" notification every minute the app stayed open. Stored, not
 * held in memory, because the task runs in its own headless context.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

const SESSION_DEAD_KEY = 'fleet_tracking_session_dead';

export async function markSessionDead(): Promise<void> {
  await AsyncStorage.setItem(SESSION_DEAD_KEY, '1').catch(() => {});
}

export async function clearSessionDead(): Promise<void> {
  await AsyncStorage.removeItem(SESSION_DEAD_KEY).catch(() => {});
}

export async function isSessionDead(): Promise<boolean> {
  try {
    return (await AsyncStorage.getItem(SESSION_DEAD_KEY)) === '1';
  } catch {
    return false;
  }
}
