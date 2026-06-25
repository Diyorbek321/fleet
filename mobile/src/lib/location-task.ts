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
import * as TaskManager from 'expo-task-manager';

import { ApiError } from './api';
import { clearTokens } from './auth';
import { meApi, type LocationPing } from './me';

/** Unique identifier for the registered background location task. */
export const LOCATION_TASK_NAME = 'fleet-watch-background-location';

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
 * connection never tears down tracking. A 401, however, means the session is
 * gone (token expired or revoked): we stop the OS location updates and clear
 * the stored tokens so a logged-out phone does not keep a foreground service
 * alive forever, hammering the backend with a dead token.
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
      // Session is invalid — surface it and shut tracking down rather than
      // silently retrying forever with a dead token.
      console.warn(
        '[location-task] 401 from location ping — session expired/revoked; stopping background tracking.',
      );
      try {
        await stopBackgroundTracking();
        await clearTokens();
      } catch {
        // Best effort: even if cleanup fails we must not crash the task.
      }
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
