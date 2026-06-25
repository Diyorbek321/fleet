import { useCallback, useEffect, useState } from 'react';
import { logger } from '@/lib/logger';

/**
 * User preference flags surfaced on the Settings page. These are currently
 * client-side only (no backend persistence yet), so we store them in
 * localStorage and restore them on load.
 */
export interface UserSettings {
  speedAlerts: boolean;
  offlineAlerts: boolean;
  maintenanceReminders: boolean;
  autoRefreshMap: boolean;
  speedInMph: boolean;
}

export const DEFAULT_SETTINGS: UserSettings = {
  speedAlerts: true,
  offlineAlerts: true,
  maintenanceReminders: true,
  autoRefreshMap: true,
  speedInMph: false,
};

const STORAGE_KEY = 'fleet_settings';

function loadSettings(): UserSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<UserSettings>;
    // Merge over defaults so newly added keys are always present and
    // unexpected/missing values fall back safely.
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch (error) {
    logger.error('Failed to read settings from storage:', error);
    return DEFAULT_SETTINGS;
  }
}

/**
 * Reads and persists user settings to localStorage. Returns the current
 * settings plus a setter that immutably updates a single key and writes through.
 */
export function useSettings() {
  const [settings, setSettings] = useState<UserSettings>(loadSettings);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (error) {
      logger.error('Failed to persist settings to storage:', error);
    }
  }, [settings]);

  const updateSetting = useCallback(
    <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => {
      setSettings((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  return { settings, updateSetting } as const;
}
