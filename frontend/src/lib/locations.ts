import { api } from '@/lib/api';
import type { TruckStatus } from '@/types';

export interface LiveLocation {
  truckId: string;
  latitude: number;
  longitude: number;
  speed: number;
  heading: number | null;
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
      recordedAt: new Date(loc.recorded_at),
    };
  }
  return map;
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
