import { api } from '@/lib/api';

export type DriverStatus = 'active' | 'inactive' | 'on_leave';

export interface Driver {
  id: string;
  name: string;
  /** Up to three numbers: the cab SIM, a personal handset, and a RU/KZ SIM for
   *  the leg past the border. `phones` is the display-ready, gap-free list. */
  phone: string | null;
  phone2: string | null;
  phone3: string | null;
  phones: string[];
  /** Cleared to carry dangerous goods. */
  adr: boolean;
  email: string | null;
  licenseNumber: string;
  licenseExpiry: string | null;
  status: DriverStatus;
  photoUrl: string | null;
  createdAt: Date;
  updatedAt: Date;
}

export interface SafetyScore {
  id: string;
  score: number;
  speedingEvents: number;
  harshBraking: number;
  harshAcceleration: number;
  idleTimeMinutes: number;
  periodStart: string;
  periodEnd: string;
}

export interface DriverDetails {
  driver: Driver;
  currentTruck: { id: string; name: string; plateNumber: string } | null;
  latestSafetyScore: SafetyScore | null;
}

interface BackendDriver {
  id: string;
  name: string;
  phone: string | null;
  phone2: string | null;
  phone3: string | null;
  adr: boolean;
  email: string | null;
  license_number: string;
  license_expiry: string | null;
  status: DriverStatus;
  photo_url: string | null;
  created_at: string;
  updated_at: string;
}

function adapt(d: BackendDriver): Driver {
  return {
    id: d.id,
    name: d.name,
    phone: d.phone,
    phone2: d.phone2 ?? null,
    phone3: d.phone3 ?? null,
    // Collapsed here rather than at each call site: every screen that shows a
    // driver's numbers wants the ones that exist, in order, with no holes.
    phones: [d.phone, d.phone2, d.phone3]
      .map((p) => p?.trim())
      .filter((p): p is string => !!p),
    adr: d.adr ?? false,
    email: d.email,
    licenseNumber: d.license_number,
    licenseExpiry: d.license_expiry,
    status: d.status,
    photoUrl: d.photo_url,
    createdAt: new Date(d.created_at),
    updatedAt: new Date(d.updated_at),
  };
}

export const driversApi = {
  list: async (): Promise<Driver[]> => {
    const data = await api<BackendDriver[]>('/api/drivers');
    return data.map(adapt);
  },
  get: async (id: string): Promise<DriverDetails> => {
    const data = await api<{
      driver: BackendDriver;
      current_truck: { id: string; name: string; plate_number: string } | null;
      latest_safety_score: {
        id: string;
        score: number;
        speeding_events: number;
        harsh_braking: number;
        harsh_acceleration: number;
        idle_time_minutes: number;
        period_start: string;
        period_end: string;
      } | null;
    }>(`/api/drivers/${id}`);
    const ss = data.latest_safety_score;
    return {
      driver: adapt(data.driver),
      currentTruck: data.current_truck
        ? {
            id: data.current_truck.id,
            name: data.current_truck.name,
            plateNumber: data.current_truck.plate_number,
          }
        : null,
      latestSafetyScore: ss
        ? {
            id: ss.id,
            score: ss.score,
            speedingEvents: ss.speeding_events,
            harshBraking: ss.harsh_braking,
            harshAcceleration: ss.harsh_acceleration,
            idleTimeMinutes: ss.idle_time_minutes,
            periodStart: ss.period_start,
            periodEnd: ss.period_end,
          }
        : null,
    };
  },
  create: async (input: {
    name: string;
    licenseNumber: string;
    phone?: string;
    phone2?: string;
    phone3?: string;
    adr?: boolean;
    status?: DriverStatus;
  }): Promise<Driver> => {
    const body: Record<string, unknown> = {
      name: input.name,
      license_number: input.licenseNumber,
      adr: input.adr ?? false,
    };
    if (input.phone) body.phone = input.phone;
    if (input.phone2) body.phone2 = input.phone2;
    if (input.phone3) body.phone3 = input.phone3;
    if (input.status) body.status = input.status;

    const data = await api<BackendDriver>('/api/drivers', { method: 'POST', body });
    return adapt(data);
  },
  update: async (
    id: string,
    patch: Partial<{
      name: string;
      phone: string;
      phone2: string;
      phone3: string;
      adr: boolean;
      licenseNumber: string;
      status: DriverStatus;
    }>,
  ): Promise<Driver> => {
    const body: Record<string, unknown> = {};
    if (patch.name !== undefined) body.name = patch.name;
    if (patch.phone !== undefined) body.phone = patch.phone;
    if (patch.phone2 !== undefined) body.phone2 = patch.phone2;
    if (patch.phone3 !== undefined) body.phone3 = patch.phone3;
    if (patch.adr !== undefined) body.adr = patch.adr;
    if (patch.licenseNumber !== undefined) body.license_number = patch.licenseNumber;
    if (patch.status !== undefined) body.status = patch.status;

    const data = await api<BackendDriver>(`/api/drivers/${id}`, { method: 'PUT', body });
    return adapt(data);
  },
  remove: async (id: string): Promise<void> => {
    await api<{ message: string }>(`/api/drivers/${id}`, { method: 'DELETE' });
  },
  createLogin: async (
    driverId: string,
    input: { email: string; password: string },
  ): Promise<{ userId: string; driverId: string; email: string }> => {
    const data = await api<{ user_id: string; driver_id: string; email: string }>(
      `/api/drivers/${driverId}/create-login`,
      { method: 'POST', body: { email: input.email, password: input.password } },
    );
    return { userId: data.user_id, driverId: data.driver_id, email: data.email };
  },
  assign: async (driverId: string, truckId: string): Promise<void> => {
    await api(`/api/drivers/${driverId}/assign`, { method: 'POST', body: { truck_id: truckId } });
  },
  unassign: async (driverId: string): Promise<void> => {
    await api(`/api/drivers/${driverId}/unassign`, { method: 'POST', body: {} });
  },
};
