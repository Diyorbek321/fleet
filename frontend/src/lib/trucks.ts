import type { Truck, TruckStatus, DashboardStats } from '@/types';
import { api } from '@/lib/api';

// ---- Backend shapes (from /api/trucks) ----

type BackendStatus = 'moving' | 'stopped' | 'idle' | 'offline' | 'maintenance';

interface BackendTruck {
  id: string;
  name: string;
  plate_number: string;
  model: string | null;
  year: number | null;
  status: BackendStatus;
  fuel_level: number;
  mileage: number;
  created_at: string;
  updated_at: string;
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

interface BackendTruckDetails extends BackendTruck {
  location: BackendLocation | null;
  driver: { id: string; name: string; phone?: string; email?: string } | null;
}

// Rich, UI-friendly shape for the truck detail page. Unlike `Truck`, this
// preserves every field the detail endpoint returns (fuel, mileage, year,
// full location, linkable driver) instead of flattening to the map model.
export interface TruckDriverRef {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
}

export interface TruckLocationDetails {
  latitude: number;
  longitude: number;
  speed: number;
  heading: number | null;
  address: string | null;
  recordedAt: Date;
}

export interface TruckDetails {
  id: string;
  name: string;
  plateNumber: string;
  model: string | null;
  year: number | null;
  status: BackendStatus;
  fuelLevel: number;
  mileage: number;
  createdAt: Date;
  updatedAt: Date;
  location: TruckLocationDetails | null;
  driver: TruckDriverRef | null;
}

function adaptDetails(d: BackendTruckDetails): TruckDetails {
  return {
    id: d.id,
    name: d.name,
    plateNumber: d.plate_number,
    model: d.model,
    year: d.year,
    status: d.status,
    fuelLevel: d.fuel_level,
    mileage: d.mileage,
    createdAt: new Date(d.created_at),
    updatedAt: new Date(d.updated_at),
    location: d.location
      ? {
          latitude: d.location.latitude,
          longitude: d.location.longitude,
          speed: d.location.speed,
          heading: d.location.heading,
          address: d.location.address,
          recordedAt: new Date(d.location.recorded_at),
        }
      : null,
    driver: d.driver
      ? {
          id: d.driver.id,
          name: d.driver.name,
          phone: d.driver.phone ?? null,
          email: d.driver.email ?? null,
        }
      : null,
  };
}

// ---- Adapters ----

function mapStatus(s: BackendStatus): TruckStatus {
  if (s === 'moving' || s === 'stopped' || s === 'offline') return s;
  return s === 'idle' ? 'stopped' : 'offline';
}

export function toFrontendTruck(b: BackendTruck, extras?: Partial<BackendTruckDetails>): Truck {
  const loc = extras?.location ?? null;
  const driver = extras?.driver ?? null;
  return {
    id: b.id,
    plateNumber: b.plate_number,
    name: b.name,
    deviceImei: '',
    model: b.model ?? undefined,
    driverName: driver?.name,
    status: mapStatus(b.status),
    speed: loc?.speed ?? 0,
    latitude: loc?.latitude ?? 0,
    longitude: loc?.longitude ?? 0,
    lastUpdate: new Date(b.updated_at),
    isEnabled: b.status !== 'offline',
  };
}

// ---- Endpoint wrappers ----

export const trucksApi = {
  list: async (): Promise<Truck[]> => {
    const data = await api<BackendTruck[]>('/api/trucks');
    return data.map((t) => toFrontendTruck(t));
  },
  get: async (id: string): Promise<Truck> => {
    const d = await api<BackendTruckDetails>(`/api/trucks/${id}`);
    return toFrontendTruck(d, d);
  },
  getDetails: async (id: string): Promise<TruckDetails> => {
    const d = await api<BackendTruckDetails>(`/api/trucks/${id}`);
    return adaptDetails(d);
  },
  create: async (input: { name: string; plateNumber: string; model?: string }): Promise<Truck> => {
    const created = await api<BackendTruck>('/api/trucks', {
      method: 'POST',
      body: {
        name: input.name,
        plate_number: input.plateNumber,
        model: input.model,
      },
    });
    return toFrontendTruck(created);
  },
  update: async (
    id: string,
    patch: Partial<{ name: string; plateNumber: string; model: string; status: BackendStatus }>,
  ): Promise<Truck> => {
    const body: Record<string, unknown> = {};
    if (patch.name !== undefined) body.name = patch.name;
    if (patch.plateNumber !== undefined) body.plate_number = patch.plateNumber;
    if (patch.model !== undefined) body.model = patch.model;
    if (patch.status !== undefined) body.status = patch.status;

    const updated = await api<BackendTruck>(`/api/trucks/${id}`, { method: 'PUT', body });
    return toFrontendTruck(updated);
  },
  remove: async (id: string): Promise<void> => {
    await api<{ message: string }>(`/api/trucks/${id}`, { method: 'DELETE' });
  },
};

// ---- Stats ----

export function calculateStats(trucks: Truck[]): DashboardStats {
  return {
    totalTrucks: trucks.length,
    movingTrucks: trucks.filter((t) => t.status === 'moving').length,
    stoppedTrucks: trucks.filter((t) => t.status === 'stopped').length,
    offlineTrucks: trucks.filter((t) => t.status === 'offline').length,
  };
}
