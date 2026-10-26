import { api } from '@/lib/api';

/** Why a truck is or is not reporting — see `app/services/truck_signal.py`. */
export type SignalState = 'ok' | 'silent' | 'never' | 'gps_off' | 'no_driver';

export interface TruckSignal {
  truckId: string;
  plateNumber: string;
  name: string;
  state: SignalState;
  lastFixAt: Date | null;
  gpsDisabledAt: Date | null;
  driverName: string | null;
  driverPhone: string | null;
  /** What the phone last said about itself; null for trackers and old APKs. */
  phoneBattery: number | null;
  phoneTracking: 'background' | 'foreground' | null;
  phoneAppVersion: string | null;
}

interface BackendTruckSignal {
  truck_id: string;
  plate_number: string;
  name: string;
  state: SignalState;
  last_fix_at: string | null;
  gps_disabled_at: string | null;
  driver_id: string | null;
  driver_name: string | null;
  driver_phone: string | null;
  phone_battery?: number | null;
  phone_tracking?: 'background' | 'foreground' | null;
  phone_app_version?: string | null;
}

export async function fetchTruckSignal(): Promise<TruckSignal[]> {
  const data = await api<BackendTruckSignal[]>('/api/trucks/signal');
  return data.map((s) => ({
    truckId: s.truck_id,
    plateNumber: s.plate_number,
    name: s.name,
    state: s.state,
    lastFixAt: s.last_fix_at ? new Date(s.last_fix_at) : null,
    gpsDisabledAt: s.gps_disabled_at ? new Date(s.gps_disabled_at) : null,
    driverName: s.driver_name,
    driverPhone: s.driver_phone,
    phoneBattery: s.phone_battery ?? null,
    phoneTracking: s.phone_tracking ?? null,
    phoneAppVersion: s.phone_app_version ?? null,
  }));
}
