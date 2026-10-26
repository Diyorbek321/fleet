/**
 * Restarting tracking when the server says this phone went quiet.
 *
 * Android stops a backgrounded app's location service on its own schedule;
 * the phone stays on and online, it just stops reporting. The server notices
 * the silence and sends a data-only, high-priority push (phone_wake.py). That
 * push is the one thing Android lets start a location service from the
 * background, so this task — run headless, with no screen — restarts it.
 *
 * Restarted even when the OS claims it is running: a service the system froze
 * still answers "started", and the server's silence is the better evidence.
 */
import * as Notifications from 'expo-notifications';
import * as TaskManager from 'expo-task-manager';

import { isTrackingActive, stopBackgroundTracking } from './location-task';
import { TRACKING_DEPS } from './tracking-os';
import { keepTrackingAlive } from './tracking-keeper';
import { isWake } from './wake';

export const WAKE_TASK_NAME = 'fleet-watch-wake';

TaskManager.defineTask(WAKE_TASK_NAME, async ({ data, error }) => {
  if (error || !isWake(data)) return;
  try {
    if ((await TRACKING_DEPS.backgroundStatus()) === 'granted' && (await isTrackingActive())) {
      await stopBackgroundTracking();
    }
    await keepTrackingAlive(TRACKING_DEPS);
  } catch {
    // Best effort: the driver and dispatcher reminders still cover this phone.
  }
});

// Registration persists across launches; repeating it on each start is harmless.
Notifications.registerTaskAsync(WAKE_TASK_NAME).catch(() => {});
