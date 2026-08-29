/**
 * Web stand-in for the background location task.
 *
 * Metro resolves `.web.ts` ahead of `.ts` when bundling for the browser, so
 * every caller keeps importing `./location-task` unchanged and no screen needs
 * a `Platform.OS === 'web'` branch.
 *
 * The native module cannot be shimmed honestly: `expo-task-manager` registers a
 * task the *operating system* invokes while the app is closed, and a browser
 * tab has no equivalent — a page that is not open cannot report anything.
 *
 * So the web build tracks only while the tab is open and in the foreground,
 * using the standard Geolocation API. That is the right shape for what the web
 * build is for — demonstrations, and a dispatcher checking the driver view from
 * a desktop — and it is deliberately *not* offered as a substitute for the
 * Android app on a real run.
 */
import { meApi } from './me';

export const LOCATION_TASK_NAME = 'fleet-watch-background-location';

export type LocationPermission = 'denied' | 'granted-foreground-only' | 'granted-background';

/** Milliseconds between pings. Matches the native task's cadence. */
const PING_INTERVAL_MS = 15_000;

let watchId: number | null = null;
let timer: ReturnType<typeof setInterval> | null = null;

function geolocation(): Geolocation | null {
  return typeof navigator !== 'undefined' && navigator.geolocation ? navigator.geolocation : null;
}

export async function requestTrackingPermissions(): Promise<LocationPermission> {
  const geo = geolocation();
  if (!geo) return 'denied';

  return new Promise((resolve) => {
    geo.getCurrentPosition(
      // Never 'granted-background': a browser tab genuinely cannot report a
      // position once it is closed, and telling the UI otherwise would put a
      // "tracking in background" state on screen that is simply untrue.
      () => resolve('granted-foreground-only'),
      () => resolve('denied'),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  });
}

export async function isTrackingActive(): Promise<boolean> {
  return watchId !== null;
}

export async function startBackgroundTracking(): Promise<void> {
  const geo = geolocation();
  if (!geo || watchId !== null) return;

  let latest: GeolocationPosition | null = null;
  watchId = geo.watchPosition(
    (position) => {
      latest = position;
    },
    () => {
      /* A revoked permission mid-session just stops the updates. */
    },
    { enableHighAccuracy: true, maximumAge: 5_000 },
  );

  // Posted on a timer rather than on every browser update: watchPosition can
  // fire many times a second, and the server wants a track, not a firehose.
  timer = setInterval(() => {
    if (!latest) return;
    void meApi
      .pingLocation({
        latitude: latest.coords.latitude,
        longitude: latest.coords.longitude,
        speed: Math.max(0, (latest.coords.speed ?? 0) * 3.6),
        heading: latest.coords.heading ?? undefined,
      })
      .catch(() => {
        /* Best-effort, exactly as on native: a dropped ping is not an error
           the driver can do anything about. */
      });
  }, PING_INTERVAL_MS);
}

export async function stopBackgroundTracking(): Promise<void> {
  const geo = geolocation();
  if (watchId !== null && geo) geo.clearWatch(watchId);
  watchId = null;
  if (timer !== null) clearInterval(timer);
  timer = null;
}
