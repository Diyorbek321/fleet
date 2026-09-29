/**
 * Noticing that the phone's location services are switched off.
 *
 * With GPS off the background task simply stops receiving fixes; nothing
 * wakes it up to say so. The server would only find out after a day of
 * silence. So while the app is open it checks the switch itself, tells the
 * driver at once with a local notification (which needs no push setup), and
 * tells the server, which warns the dispatcher if it stays off.
 *
 * Only a change is notified or reported, so a check every minute costs
 * nothing while the switch stays where it is.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Location from 'expo-location';
import * as Notifications from 'expo-notifications';

import i18n from '../i18n';
import { meApi } from './me';

// Two keys, because the two things can disagree: the driver has been told the
// GPS is off, but the phone is also offline and the server has not heard yet.
// One key would re-notify the driver every minute until the report got through.
const LAST_SEEN_KEY = 'fleet_gps_last_seen';
const LAST_REPORTED_KEY = 'fleet_gps_last_reported';

async function read(key: string): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(key);
  } catch {
    return null;
  }
}

async function notifyGpsOff(): Promise<void> {
  try {
    await Notifications.scheduleNotificationAsync({
      content: { title: i18n.t('gps.offTitle'), body: i18n.t('gps.offBody') },
      trigger: null,
    });
  } catch {
    // Notifications denied: the banner on the home screen still shows it.
  }
}

/**
 * Check the switch, and report it if it changed. Returns whether GPS is on.
 *
 * Never throws: this runs on a timer, and a failed report is retried by the
 * next check because the stored value is only updated after a success.
 */
export async function checkGpsServices(): Promise<boolean> {
  let enabled: boolean;
  try {
    enabled = await Location.hasServicesEnabledAsync();
  } catch {
    return true; // cannot tell — do not raise an alarm on a guess
  }

  const state = String(enabled);
  if ((await read(LAST_SEEN_KEY)) !== state) {
    if (!enabled) await notifyGpsOff();
    await AsyncStorage.setItem(LAST_SEEN_KEY, state).catch(() => {});
  }
  if ((await read(LAST_REPORTED_KEY)) !== state) {
    try {
      await meApi.reportGpsStatus(enabled);
      await AsyncStorage.setItem(LAST_REPORTED_KEY, state);
    } catch {
      // Offline or signed out: the next check tries again.
    }
  }
  return enabled;
}

/**
 * Ask Android to switch location on (the system "turn on location" dialog).
 * iOS has no such prompt; the driver has to go to Settings.
 */
export async function askToEnableGps(): Promise<void> {
  try {
    await Location.enableNetworkProviderAsync();
  } catch {
    // Declined or unsupported — the banner stays until GPS is on.
  }
}

export async function resetGpsReport(): Promise<void> {
  await AsyncStorage.multiRemove([LAST_SEEN_KEY, LAST_REPORTED_KEY]).catch(() => {});
}
