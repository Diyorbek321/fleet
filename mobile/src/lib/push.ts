import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { apiFetch } from './api';

/**
 * Registering this device for push notifications.
 *
 * The backend has stored push tokens and resolved them on every queue-status
 * change for a while, but nothing ever produced one: the app never called
 * `/api/me/push-token`, so the table stayed empty and the whole notification
 * path was dead from this end. This module is that missing half.
 *
 * Everything here is best-effort. A driver who declines the permission, or a
 * build without an EAS project id, must still get a working app — losing
 * notifications is worse than nothing, but far better than a login that
 * crashes.
 */

const REGISTERED_TOKEN_KEY = 'fleet_driver_push_token';

/** Android shows nothing without a channel; the OS drops the notification silently. */
const ANDROID_CHANNEL_ID = 'default';

/**
 * Expo needs the EAS project id to mint a token for this app.
 *
 * `eas build` writes it into app.json as `expo.extra.eas.projectId` once the
 * project has been linked with `eas init`. Reading it defensively rather than
 * assuming it: without it `getExpoPushTokenAsync` throws, and a crash on the
 * login path would be a far worse bug than the missing notifications.
 */
function easProjectId(): string | undefined {
  const extra = Constants.expoConfig?.extra as Record<string, any> | undefined;
  return (extra?.eas?.projectId as string | undefined) ?? Constants.easConfig?.projectId;
}

async function ensureAndroidChannel(): Promise<void> {
  if (Platform.OS !== 'android') return;
  await Notifications.setNotificationChannelAsync(ANDROID_CHANNEL_ID, {
    name: 'Fleet Watch',
    importance: Notifications.AndroidImportance.HIGH,
    vibrationPattern: [0, 250, 250, 250],
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
  });
}

async function ensurePermission(): Promise<boolean> {
  const existing = await Notifications.getPermissionsAsync();
  if (existing.granted) return true;
  // Only ask when we have not been refused outright — re-prompting a driver
  // who said no does nothing on either platform except waste a launch.
  if (!existing.canAskAgain) return false;
  const asked = await Notifications.requestPermissionsAsync();
  return asked.granted;
}

/**
 * Register this device with the backend. Safe to call on every launch.
 *
 * Tokens are not stable — they rotate on reinstall, on restore to a new phone,
 * and occasionally on their own — so this runs after every sign-in rather than
 * once ever. The backend upserts on the token value and re-points it at the
 * current user, which also covers two drivers sharing one handset.
 *
 * Returns the registered token, or null if this device will not receive pushes.
 */
export async function registerPushToken(): Promise<string | null> {
  try {
    if (!(await ensurePermission())) return null;
    await ensureAndroidChannel();

    const projectId = easProjectId();
    if (!projectId) {
      // Expected in bare `npm start` runs; in a shipped build it means the
      // project was never linked, and no driver will ever be notified.
      console.warn(
        '[push] no EAS project id — run `eas init`. Push notifications are disabled.',
      );
      return null;
    }

    const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId });
    await apiFetch('/api/me/push-token', {
      method: 'POST',
      body: JSON.stringify({ token, platform: Platform.OS }),
    });
    await AsyncStorage.setItem(REGISTERED_TOKEN_KEY, token).catch(() => {});
    return token;
  } catch (e) {
    // Simulators have no push token, permissions can be revoked mid-session,
    // and the network can be down. None of it should surface to the driver.
    console.warn('[push] registration failed', e);
    return null;
  }
}

/**
 * Drop this device's registration. Call on sign-out.
 *
 * Without it, a driver who hands the phone back at the end of a contract keeps
 * receiving another company's border-queue alerts — the token stays pointed at
 * their old user and the backend has no way to know the app was signed out.
 * Deletes the exact token we registered, not "all tokens for this user", so a
 * driver signed in on two devices only loses the one they signed out of.
 */
export async function unregisterPushToken(): Promise<void> {
  try {
    const token = await AsyncStorage.getItem(REGISTERED_TOKEN_KEY);
    if (!token) return;
    await apiFetch('/api/me/push-token', {
      method: 'DELETE',
      body: JSON.stringify({ token }),
    });
  } catch {
    // Best-effort: the local session is being torn down regardless. The
    // backend also drops tokens Expo reports as unregistered, so a leftover
    // row is cleaned up the first time it fails to deliver.
  } finally {
    await AsyncStorage.removeItem(REGISTERED_TOKEN_KEY).catch(() => {});
  }
}
