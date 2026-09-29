import type { Truck, TruckStatus, TrailerVolume, DashboardStats } from '@/types';
import { api } from '@/lib/api';

// ---- Backend shapes (from /api/trucks) ----

type BackendStatus = 'moving' | 'stopped' | 'idle' | 'offline' | 'maintenance';

interface BackendTruck {
  id: string;
  name: string;
  plate_number: string;
  model: string | null;
  year: number | null;
  tractor_brand: string | null;
  trailer_brand: string | null;
  trailer_volume: TrailerVolume | null;
  insurance_expiry?: string | null;
  gps_disabled_at?: string | null;
  status: BackendStatus;
  is_enabled: boolean;
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
  tractorBrand: string | null;
  trailerBrand: string | null;
  trailerVolume: TrailerVolume | null;
  insuranceExpiry: string | null;
  /** When the driver's phone reported its GPS switched off; null while on. */
  gpsDisabledAt: Date | null;
  status: BackendStatus;
  isEnabled: boolean;
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
    tractorBrand: d.tractor_brand,
    trailerBrand: d.trailer_brand,
    trailerVolume: d.trailer_volume,
    insuranceExpiry: d.insurance_expiry ?? null,
    gpsDisabledAt: d.gps_disabled_at ? new Date(d.gps_disabled_at) : null,
    status: d.status,
    isEnabled: d.is_enabled,
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
    model: b.model ?? undefined,
    tractorBrand: b.tractor_brand ?? undefined,
    trailerBrand: b.trailer_brand ?? undefined,
    trailerVolume: b.trailer_volume ?? undefined,
    insuranceExpiry: b.insurance_expiry ?? null,
    driverName: driver?.name,
    status: mapStatus(b.status),
    speed: loc?.speed ?? 0,
    latitude: loc?.latitude ?? 0,
    longitude: loc?.longitude ?? 0,
    address: loc?.address ?? null,
    lastUpdate: new Date(b.updated_at),
    // The dispatcher's switch, which the backend stores on its own. It used
    // to be derived from `status`, so a truck with no GPS fix — every truck on
    // the day it is added — read as switched off and was filtered out of the
    // map and the fuel and service pickers.
    isEnabled: b.is_enabled,
  };
}

/** Everything the truck form collects. One shape for create and patch, so a
 *  field added to the form cannot reach one endpoint and not the other. */
export interface TruckInput {
  /** Optional: left out, the backend names the truck after its plate. */
  name?: string;
  plateNumber: string;
  model?: string;
  tractorBrand?: string;
  trailerBrand?: string;
  trailerVolume?: TrailerVolume;
  /** ISO date; null clears it on an edit. */
  insuranceExpiry?: string | null;
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
  create: async (input: TruckInput): Promise<Truck> => {
    const created = await api<BackendTruck>('/api/trucks', {
      method: 'POST',
      body: {
        name: input.name,
        plate_number: input.plateNumber,
        model: input.model,
        tractor_brand: input.tractorBrand,
        trailer_brand: input.trailerBrand,
        trailer_volume: input.trailerVolume,
        insurance_expiry: input.insuranceExpiry || null,
      },
    });
    return toFrontendTruck(created);
  },
  update: async (
    id: string,
    patch: Partial<TruckInput & { status: BackendStatus; isEnabled: boolean }>,
  ): Promise<Truck> => {
    const body: Record<string, unknown> = {};
    if (patch.name !== undefined) body.name = patch.name;
    if (patch.plateNumber !== undefined) body.plate_number = patch.plateNumber;
    if (patch.model !== undefined) body.model = patch.model;
    if (patch.tractorBrand !== undefined) body.tractor_brand = patch.tractorBrand;
    if (patch.trailerBrand !== undefined) body.trailer_brand = patch.trailerBrand;
    if (patch.trailerVolume !== undefined) body.trailer_volume = patch.trailerVolume;
    if (patch.insuranceExpiry !== undefined) body.insurance_expiry = patch.insuranceExpiry || null;
    if (patch.status !== undefined) body.status = patch.status;
    if (patch.isEnabled !== undefined) body.is_enabled = patch.isEnabled;

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
