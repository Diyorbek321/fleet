import { api } from '@/lib/api';
import type { TruckStatus } from '@/types';

export interface LiveLocation {
  truckId: string;
  latitude: number;
  longitude: number;
  speed: number;
  heading: number | null;
  /** "Qozog'iston, Sariog'ash" — filled by the backend's labelling job.
   *  Null until that job has seen this position, and on every WebSocket
   *  update, which carries coordinates only. */
  address: string | null;
  recordedAt: Date;
}

interface BackendLocation {
  truck_id: string;
  latitude: number;
  longitude: number;
  speed: number;
  heading: number | null;
  address: string | null;
  recorded_at: string;
}

export async function fetchTruckLocations(): Promise<Record<string, LiveLocation>> {
  const data = await api<BackendLocation[]>('/api/trucks/locations');
  const map: Record<string, LiveLocation> = {};
  for (const loc of data) {
    map[loc.truck_id] = {
      truckId: loc.truck_id,
      latitude: loc.latitude,
      longitude: loc.longitude,
      speed: loc.speed,
      heading: loc.heading,
      address: loc.address,
      recordedAt: new Date(loc.recorded_at),
    };
  }
  return map;
}

/**
 * Place names only, keyed by truck id.
 *
 * Deliberately separate from the live position stream: the WebSocket is the
 * source of truth for where a truck *is*, and re-seeding the whole location
 * map every few minutes would rewind every marker to the last REST snapshot.
 * Labels change slowly (the backend relabels every 5 minutes), so they are
 * polled on their own and merged in as text.
 */
export async function fetchTruckLocationLabels(): Promise<Record<string, string>> {
  const data = await api<BackendLocation[]>('/api/trucks/locations');
  const labels: Record<string, string> = {};
  for (const loc of data) {
    if (loc.address) labels[loc.truck_id] = loc.address;
  }
  return labels;
}

// Match the backend's app/services/gps.py::status_from_speed.
export function statusFromSpeed(speed: number): TruckStatus {
  if (speed >= 5) return 'moving';
  if (speed < 0.5) return 'stopped';
  // 'idle' in backend — we collapse to 'stopped' in the frontend vocabulary
  return 'stopped';
}

// Shape of the WebSocket broadcast from app/routers/gps.py
export interface LocationUpdateMessage {
  type: 'truck_location_update';
  truck_id: string;
  lat: number;
  lng: number;
  speed: number;
  heading: number | null;
  recorded_at: string | null;
}
