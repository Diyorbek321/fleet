/**
 * The update gate: is this APK older than the server's minimum?
 *
 * APKs are passed from phone to phone, so a driver can run a build months
 * old — one without the standing-still heartbeat made parked trucks look dead
 * for weeks. The server names a minimum (GET /api/app/driver-version); below
 * it the app shows only an "update" screen with the download link.
 */
import * as Application from 'expo-application';

import { apiFetch } from './api';

export interface DriverVersion {
  min_version: string;
  latest_version: string;
  download_url: string;
}

/** Negative when ``a`` is older than ``b``. Missing parts count as zero. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0);
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

/** Never blocks on a guess: no minimum set, or a version it cannot read. */
export function isOutdated(current: string | null, minimum: string): boolean {
  if (!current || !minimum.trim()) return false;
  return compareVersions(current, minimum) < 0;
}

export function currentVersion(): string | null {
  return Application.nativeApplicationVersion;
}

export async function fetchDriverVersion(): Promise<DriverVersion> {
  return apiFetch<DriverVersion>('/api/app/driver-version');
}
