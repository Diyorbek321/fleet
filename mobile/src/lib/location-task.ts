/**
 * Background GPS tracking.
 *
 * The foreground `watchPositionAsync` in older builds only reported while the
 * app was open. This module registers an OS-level background location task
 * (via TaskManager) and an Android foreground service so the driver's position
 * keeps reaching the dispatcher even when the app is backgrounded or the screen
 * is off, for the duration of a shift / while sharing is enabled.
 *
 * The task callback runs in a separate JS context that does NOT share the
 * app's in-memory state, so it reads the auth token from storage on every
 * batch before pinging `POST /api/me/location`.
 */
import * as Location from 'expo-location';
import * as Notifications from 'expo-notifications';
import * as TaskManager from 'expo-task-manager';

import { ApiError } from './api';
import { meApi, type LocationPing } from './me';

/** Unique identifier for the registered background location task. */
export const LOCATION_TASK_NAME = 'fleet-watch-background-location';

// Make sure the "tracking stopped" alert actually surfaces as a system
// notification even if the app happens to be in the foreground when it
// fires. This module can run inside a headless JS instance spun up purely to
// service the background task (app fully backgrounded/killed), so we
// configure the handler here rather than assuming a screen-level provider
// has already done it.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * Alerts the driver that background tracking stopped itself because the
 * session is dead. Fired from the headless task context described in the
 * module docstring above, which does NOT share React/i18n state with the
 * foreground app, so the copy here is intentionally hardcoded (a live
 * i18next instance may not be initialized in that context) rather than
 * routed through `react-i18next`.
 *
 * Best-effort: notification permission is requested up front in
 * {@link requestTrackingPermissions} (which runs in the foreground, where a
 * permission prompt can actually be shown); if it was never granted this
 * simply no-ops rather than crashing the task.
 */
async function notifyTrackingStopped(): Promise<void> {
  try {
    await Notifications.scheduleNotificationAsync({
      content: {
        title: 'Location sharing stopped',
        body: 'Fleet Watch stopped sharing your location — please reopen the app and sign in again.',
      },
      trigger: null,
    });
  } catch {
    // Best effort: a failed/denied notification must not crash the task.
  }
}

/** How the background updates are sampled. Tuned for trucking: a ping every
 *  ~15s or every 50m, balanced accuracy to preserve battery. */
const UPDATE_OPTIONS: Location.LocationTaskOptions = {
  accuracy: Location.Accuracy.Balanced,
  timeInterval: 15000,
  distanceInterval: 50,
  // Keep the OS from killing the process while a shift is active (Android).
  foregroundService: {
    notificationTitle: 'Fleet Watch',
    notificationBody: 'Sharing your location with your dispatcher',
    notificationColor: '#2563eb',
  },
  // iOS: surface the blue bar / pause behaviour sensibly.
  pausesUpdatesAutomatically: false,
  showsBackgroundLocationIndicator: true,
  activityType: Location.ActivityType.AutomotiveNavigation,
};

interface LocationTaskData {
  locations: Location.LocationObject[];
}

/**
 * The background task. Receives batched location samples from the OS and pings
 * the backend (the request carries the stored bearer token, attached by
 * `apiFetch`).
 *
 * Transient errors (network failure, 5xx) are swallowed per-batch so a flaky
 * connection never tears down tracking. A 401 here means `apiFetch`'s refresh
 * attempt also failed (refresh token expired or revoked); we stop the OS
 * location updates so a dead session doesn't keep a foreground service alive
 * hammering the backend, but we deliberately leave the stored tokens in place
 * — the driver stays signed in on the app shell and can re-login manually
 * when they next open it, instead of being silently kicked to the login
 * screen mid-shift.
 */
TaskManager.defineTask(LOCATION_TASK_NAME, async ({ data, error }) => {
  if (error) return;

  const { locations } = (data ?? {}) as LocationTaskData;
  if (!locations || locations.length === 0) return;

  // Only the freshest sample matters to the dispatcher; avoid flooding the
  // backend with the whole batch.
  const latest = locations[locations.length - 1];
  const ping: LocationPing = {
    latitude: latest.coords.latitude,
    longitude: latest.coords.longitude,
    speed: latest.coords.speed ?? 0,
    heading: latest.coords.heading ?? null,
  };

  try {
    await meApi.pingLocation(ping);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      // Refresh in `apiFetch` already failed — session is truly dead. Stop
      // the OS updates so we don't keep a foreground service alive pinging
      // with a dead token, but do NOT clear tokens: the driver stays
      // "logged in" on the app shell and can sign out or re-login manually.
      console.warn(
        '[location-task] 401 from location ping after refresh — stopping background tracking (session left intact).',
      );
      try {
        await stopBackgroundTracking();
      } catch {
        // Best effort: even if cleanup fails we must not crash the task.
      }
      // The app's own UI has no way to notice tracking died on its own
      // (the toggle only reflects OS state when explicitly re-checked), so
      // this is the driver's only real-time signal that sharing is down.
      await notifyTrackingStopped();
      return;
    }
    // Transient failure (network/5xx): fire-and-forget, keep tracking alive.
  }
});

export type LocationPermission =
  | 'granted-background'
  | 'granted-foreground-only'
  | 'denied';

/**
 * Request the permissions needed for tracking. Foreground is required at a
 * minimum; background unlocks true always-on tracking. Returns which level
 * was actually granted so the caller can inform the driver.
 */
export async function requestTrackingPermissions(): Promise<LocationPermission> {
  const foreground = await Location.requestForegroundPermissionsAsync();
  if (foreground.status !== 'granted') return 'denied';

  // Best effort, and deliberately not blocking on the result: this is what
  // lets `notifyTrackingStopped` actually surface a system notification
  // later if the background task has to self-stop on a dead session. Asked
  // here (foreground, driver-initiated) because that's the only reliable
  // place the OS will show a permission prompt — a headless background task
  // generally cannot.
  await Notifications.requestPermissionsAsync().catch(() => {});

  const background = await Location.requestBackgroundPermissionsAsync();
  return background.status === 'granted'
    ? 'granted-background'
    : 'granted-foreground-only';
}

/** Whether the background location updates are currently running. */
export async function isTrackingActive(): Promise<boolean> {
  try {
    return await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME);
  } catch {
    return false;
  }
}

/**
 * Begin OS-level background location updates. Safe to call when already
 * running (the OS treats it as an options update). Assumes permissions have
 * already been granted via {@link requestTrackingPermissions}.
 */
export async function startBackgroundTracking(): Promise<void> {
  if (await isTrackingActive()) return;
  await Location.startLocationUpdatesAsync(LOCATION_TASK_NAME, UPDATE_OPTIONS);
}

/** Stop background location updates if they are running. */
export async function stopBackgroundTracking(): Promise<void> {
  if (await isTrackingActive()) {
    await Location.stopLocationUpdatesAsync(LOCATION_TASK_NAME);
  }
}
