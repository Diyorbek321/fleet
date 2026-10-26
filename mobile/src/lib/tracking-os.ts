/** The OS calls behind `keepTrackingAlive`, shared by the screen and the wake task. */
import * as Location from 'expo-location';

import { isTrackingActive, startBackgroundTracking } from './location-task';
import type { TrackingDeps } from './tracking-keeper';
import { isSessionDead } from './tracking-session';

export const TRACKING_DEPS: TrackingDeps = {
  backgroundStatus: async () => (await Location.getBackgroundPermissionsAsync()).status,
  foregroundStatus: async () => (await Location.getForegroundPermissionsAsync()).status,
  isRunning: isTrackingActive,
  sessionDead: isSessionDead,
  start: startBackgroundTracking,
};
