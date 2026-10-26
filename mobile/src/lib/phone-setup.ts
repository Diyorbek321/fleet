/**
 * The two phone settings that keep tracking alive with the app closed.
 *
 * Granting "always" location is not enough on most phones drivers carry.
 * Android's battery optimisation, and on Xiaomi, Huawei, Oppo and Vivo the
 * maker's own "autostart" list, stop a backgrounded app's location service
 * within minutes of the screen going off — which is how most of the pilot
 * fleet went dark. Neither can be read back without native code, so the
 * driver is walked through both once and confirms; the server's silence
 * reminders catch anyone who did not.
 */
import { Linking, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as IntentLauncher from 'expo-intent-launcher';

const SETUP_DONE_KEY = 'fleet_phone_setup_done';
const PACKAGE = 'com.fleetwatch.driver';

export interface ActivityTarget {
  packageName: string;
  className: string;
}

/** Each maker's autostart screen, newest ROM first; the next is tried if one is missing. */
const AUTOSTART: [RegExp, ActivityTarget[]][] = [
  [
    /xiaomi|redmi|poco/i,
    [
      {
        packageName: 'com.miui.securitycenter',
        className: 'com.miui.permcenter.autostart.AutoStartManagementActivity',
      },
    ],
  ],
  [
    /huawei|honor/i,
    [
      {
        packageName: 'com.huawei.systemmanager',
        className: 'com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity',
      },
      {
        packageName: 'com.huawei.systemmanager',
        className: 'com.huawei.systemmanager.optimize.process.ProtectActivity',
      },
    ],
  ],
  [
    /oppo|realme|oneplus/i,
    [
      {
        packageName: 'com.coloros.safecenter',
        className: 'com.coloros.safecenter.permission.startup.StartupAppListActivity',
      },
      {
        packageName: 'com.coloros.safecenter',
        className: 'com.coloros.safecenter.startupapp.StartupAppListActivity',
      },
    ],
  ],
  [
    /vivo|iqoo/i,
    [
      {
        packageName: 'com.vivo.permissionmanager',
        className: 'com.vivo.permissionmanager.activity.BgStartUpManagerActivity',
      },
    ],
  ],
];

export function autostartTargets(manufacturer: string | undefined): ActivityTarget[] {
  if (!manufacturer) return [];
  return AUTOSTART.find(([pattern]) => pattern.test(manufacturer))?.[1] ?? [];
}

export function needsAutostart(manufacturer: string | undefined): boolean {
  return autostartTargets(manufacturer).length > 0;
}

/** The phone's maker, as Android reports it; undefined elsewhere. */
export function phoneManufacturer(): string | undefined {
  if (Platform.OS !== 'android') return undefined;
  const constants = Platform.constants as { Manufacturer?: string; Brand?: string };
  return constants.Manufacturer ?? constants.Brand;
}

/**
 * The system "let this app run in the background?" dialog, or the list of
 * apps under battery optimisation where the dialog is unavailable.
 */
export async function openBatterySettings(): Promise<void> {
  try {
    await IntentLauncher.startActivityAsync(
      IntentLauncher.ActivityAction.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
      { data: `package:${PACKAGE}` },
    );
  } catch {
    try {
      await IntentLauncher.startActivityAsync(
        IntentLauncher.ActivityAction.IGNORE_BATTERY_OPTIMIZATION_SETTINGS,
      );
    } catch {
      await Linking.openSettings();
    }
  }
}

/** The maker's autostart list; the app's own settings page when none opens. */
export async function openAutostartSettings(): Promise<void> {
  for (const target of autostartTargets(phoneManufacturer())) {
    try {
      await IntentLauncher.startActivityAsync('android.intent.action.MAIN', target);
      return;
    } catch {
      // This ROM moved the screen; try the next known place.
    }
  }
  await Linking.openSettings();
}

/** Android only: iOS has neither setting and keeps location apps running. */
export async function needsPhoneSetup(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  try {
    return (await AsyncStorage.getItem(SETUP_DONE_KEY)) !== '1';
  } catch {
    return true;
  }
}

export async function markPhoneSetupDone(): Promise<void> {
  await AsyncStorage.setItem(SETUP_DONE_KEY, '1').catch(() => {});
}
