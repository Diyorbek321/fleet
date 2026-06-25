import { api } from '@/lib/api';

export interface Geofence {
  id: string;
  name: string;
  category: string | null;
  centerLat: number;
  centerLng: number;
  radiusM: number;
  active: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export type GeofenceEventType = 'enter' | 'exit';

export interface GeofenceEvent {
  id: string;
  geofenceId: string;
  truckId: string;
  event: GeofenceEventType;
  latitude: number;
  longitude: number;
  recordedAt: Date;
}

interface BackendGeofence {
  id: string;
  name: string;
  category: string | null;
  center_lat: number;
  center_lng: number;
  radius_m: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

interface BackendGeofenceEvent {
  id: string;
  geofence_id: string;
  truck_id: string;
  event: GeofenceEventType;
  latitude: number;
  longitude: number;
  recorded_at: string;
}

function adapt(g: BackendGeofence): Geofence {
  return {
    id: g.id,
    name: g.name,
    category: g.category,
    centerLat: Number(g.center_lat),
    centerLng: Number(g.center_lng),
    radiusM: Number(g.radius_m),
    active: g.active,
    createdAt: new Date(g.created_at),
    updatedAt: new Date(g.updated_at),
  };
}

function adaptEvent(e: BackendGeofenceEvent): GeofenceEvent {
  return {
    id: e.id,
    geofenceId: e.geofence_id,
    truckId: e.truck_id,
    event: e.event,
    latitude: Number(e.latitude),
    longitude: Number(e.longitude),
    recordedAt: new Date(e.recorded_at),
  };
}

export interface GeofenceInput {
  name: string;
  category?: string;
  centerLat: number;
  centerLng: number;
  radiusM: number;
  active?: boolean;
}

function toBody(input: Partial<GeofenceInput>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.category !== undefined) body.category = input.category || null;
  if (input.centerLat !== undefined) body.center_lat = input.centerLat;
  if (input.centerLng !== undefined) body.center_lng = input.centerLng;
  if (input.radiusM !== undefined) body.radius_m = input.radiusM;
  if (input.active !== undefined) body.active = input.active;
  return body;
}

export const geofencesApi = {
  list: async (): Promise<Geofence[]> => {
    const data = await api<BackendGeofence[]>('/api/geofences');
    return data.map(adapt);
  },
  create: async (input: GeofenceInput): Promise<Geofence> => {
    const data = await api<BackendGeofence>('/api/geofences', { method: 'POST', body: toBody(input) });
    return adapt(data);
  },
  update: async (id: string, patch: Partial<GeofenceInput>): Promise<Geofence> => {
    const data = await api<BackendGeofence>(`/api/geofences/${id}`, { method: 'PUT', body: toBody(patch) });
    return adapt(data);
  },
  remove: async (id: string): Promise<void> => {
    await api<void>(`/api/geofences/${id}`, { method: 'DELETE' });
  },
  events: async (limit = 50): Promise<GeofenceEvent[]> => {
    const data = await api<BackendGeofenceEvent[]>(`/api/geofences/events?limit=${limit}`);
    return data.map(adaptEvent);
  },
};
