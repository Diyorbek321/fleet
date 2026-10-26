/**
 * What the phone says about itself next to its position: battery, whether it
 * tracks in the background or only while the app is open, and the app
 * version. The panel shows it beside "no signal", so the dispatcher can tell
 * a flat battery from a revoked permission from an APK that is months old.
 */
import * as Application from 'expo-application';
import * as Battery from 'expo-battery';

export type TrackingMode = 'background' | 'foreground';

export interface PhoneState {
  battery?: number;
  tracking: TrackingMode;
  app_version?: string;
}

export async function phoneState(tracking: TrackingMode): Promise<PhoneState> {
  let battery: number | undefined;
  try {
    const level = await Battery.getBatteryLevelAsync();
    // -1 when the platform cannot tell; leave the stored value alone then.
    if (level >= 0) battery = Math.round(level * 100) / 100;
  } catch {
    // Reading the battery must never cost a position.
  }
  return {
    battery,
    tracking,
    app_version: Application.nativeApplicationVersion ?? undefined,
  };
}
