import { api } from '@/lib/api';

export type TripStatus =
  | 'draft'
  | 'planned'
  | 'loading'
  | 'en_route'
  | 'at_border'
  | 'delivered'
  | 'cancelled';

export type TripEventType =
  | 'created'
  | 'status_change'
  | 'note'
  | 'border_arrival'
  | 'border_clear'
  | 'pod';

export interface TripEvent {
  id: string;
  event: TripEventType;
  fromStatus: TripStatus | null;
  toStatus: TripStatus | null;
  note: string | null;
  latitude: number | null;
  longitude: number | null;
  recordedAt: string;
}

export interface Trip {
  id: string;
  reference: string;
  truckId: string | null;
  driverId: string | null;
  status: TripStatus;
  shipper: string | null;
  consignee: string | null;
  originName: string | null;
  destinationName: string | null;
  cargoDescription: string | null;
  cargoWeightKg: number | null;
  isReefer: boolean;
  rate: number;
  currency: string;
  plannedDistanceKm: number | null;
  scheduledStart: string | null;
  scheduledEnd: string | null;
  startedAt: string | null;
  deliveredAt: string | null;
  notes: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface TripDetails extends Trip {
  events: TripEvent[];
  truckName: string | null;
  truckPlate: string | null;
  driverName: string | null;
}

export interface TripDocument {
  id: string;
  tripId: string;
  category: string;
  caption: string | null;
  contentType: string;
  sizeBytes: number;
  url: string;
  uploadedAt: string;
  driverName: string | null;
}

interface BackendTripDocument {
  id: string;
  trip_id: string;
  category: string;
  caption: string | null;
  content_type: string;
  size_bytes: number;
  url: string;
  uploaded_at: string;
  driver_name: string | null;
}

function adaptDocument(d: BackendTripDocument): TripDocument {
  return {
    id: d.id,
    tripId: d.trip_id,
    category: d.category,
    caption: d.caption,
    contentType: d.content_type,
    sizeBytes: d.size_bytes,
    url: d.url,
    uploadedAt: d.uploaded_at,
    driverName: d.driver_name,
  };
}

export interface TripPnL {
  tripId: string;
  reference: string;
  status: TripStatus;
  currency: string;
  revenue: number;
  fuelCost: number;
  expenseCost: number;
  totalCost: number;
  profit: number;
  marginPct: number;
}

interface BackendTrip {
  id: string;
  reference: string;
  truck_id: string | null;
  driver_id: string | null;
  status: TripStatus;
  shipper: string | null;
  consignee: string | null;
  origin_name: string | null;
  destination_name: string | null;
  cargo_description: string | null;
  cargo_weight_kg: number | null;
  is_reefer: boolean;
  rate: number;
  currency: string;
  planned_distance_km: number | null;
  scheduled_start: string | null;
  scheduled_end: string | null;
  started_at: string | null;
  delivered_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface BackendTripDetails extends BackendTrip {
  events: Array<{
    id: string;
    event: TripEventType;
    from_status: TripStatus | null;
    to_status: TripStatus | null;
    note: string | null;
    latitude: number | null;
    longitude: number | null;
    recorded_at: string;
  }>;
  truck_name: string | null;
  truck_plate: string | null;
  driver_name: string | null;
}

function adapt(t: BackendTrip): Trip {
  return {
    id: t.id,
    reference: t.reference,
    truckId: t.truck_id,
    driverId: t.driver_id,
    status: t.status,
    shipper: t.shipper,
    consignee: t.consignee,
    originName: t.origin_name,
    destinationName: t.destination_name,
    cargoDescription: t.cargo_description,
    cargoWeightKg: t.cargo_weight_kg,
    isReefer: t.is_reefer,
    rate: Number(t.rate),
    currency: t.currency,
    plannedDistanceKm: t.planned_distance_km,
    scheduledStart: t.scheduled_start,
    scheduledEnd: t.scheduled_end,
    startedAt: t.started_at,
    deliveredAt: t.delivered_at,
    notes: t.notes,
    createdAt: t.created_at,
    updatedAt: t.updated_at,
  };
}

function adaptDetails(t: BackendTripDetails): TripDetails {
  return {
    ...adapt(t),
    truckName: t.truck_name,
    truckPlate: t.truck_plate,
    driverName: t.driver_name,
    events: t.events.map((e) => ({
      id: e.id,
      event: e.event,
      fromStatus: e.from_status,
      toStatus: e.to_status,
      note: e.note,
      latitude: e.latitude,
      longitude: e.longitude,
      recordedAt: e.recorded_at,
    })),
  };
}

export interface TripCreateInput {
  truckId?: string;
  driverId?: string | null;
  shipper?: string;
  consignee?: string;
  originName?: string;
  destinationName?: string;
  cargoDescription?: string;
  cargoWeightKg?: number;
  isReefer?: boolean;
  rate?: number;
  currency?: string;
  plannedDistanceKm?: number;
  notes?: string;
}

function toBody(input: TripCreateInput): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.truckId) body.truck_id = input.truckId;
  if (input.driverId !== undefined) body.driver_id = input.driverId;
  if (input.shipper) body.shipper = input.shipper;
  if (input.consignee) body.consignee = input.consignee;
  if (input.originName) body.origin_name = input.originName;
  if (input.destinationName) body.destination_name = input.destinationName;
  if (input.cargoDescription) body.cargo_description = input.cargoDescription;
  if (input.cargoWeightKg !== undefined) body.cargo_weight_kg = input.cargoWeightKg;
  if (input.isReefer !== undefined) body.is_reefer = input.isReefer;
  if (input.rate !== undefined) body.rate = input.rate;
  if (input.currency) body.currency = input.currency;
  if (input.plannedDistanceKm !== undefined) body.planned_distance_km = input.plannedDistanceKm;
  if (input.notes) body.notes = input.notes;
  return body;
}

export const tripsApi = {
  list: async (status?: TripStatus): Promise<Trip[]> => {
    const q = status ? `?status=${status}` : '';
    const data = await api<BackendTrip[]>(`/api/trips${q}`);
    return data.map(adapt);
  },
  get: async (id: string): Promise<TripDetails> => {
    const data = await api<BackendTripDetails>(`/api/trips/${id}`);
    return adaptDetails(data);
  },
  create: async (input: TripCreateInput): Promise<TripDetails> => {
    const data = await api<BackendTripDetails>('/api/trips', { method: 'POST', body: toBody(input) });
    return adaptDetails(data);
  },
  update: async (id: string, input: TripCreateInput): Promise<TripDetails> => {
    const data = await api<BackendTripDetails>(`/api/trips/${id}`, { method: 'PUT', body: toBody(input) });
    return adaptDetails(data);
  },
  advance: async (
    id: string,
    toStatus: TripStatus,
    opts: { note?: string; latitude?: number; longitude?: number } = {},
  ): Promise<TripDetails> => {
    const data = await api<BackendTripDetails>(`/api/trips/${id}/advance`, {
      method: 'POST',
      body: { to_status: toStatus, note: opts.note, latitude: opts.latitude, longitude: opts.longitude },
    });
    return adaptDetails(data);
  },
  pnl: async (id: string): Promise<TripPnL> => {
    const d = await api<{
      trip_id: string;
      reference: string;
      status: TripStatus;
      currency: string;
      revenue: number;
      fuel_cost: number;
      expense_cost: number;
      total_cost: number;
      profit: number;
      margin_pct: number;
    }>(`/api/trips/${id}/pnl`);
    return {
      tripId: d.trip_id,
      reference: d.reference,
      status: d.status,
      currency: d.currency,
      revenue: d.revenue,
      fuelCost: d.fuel_cost,
      expenseCost: d.expense_cost,
      totalCost: d.total_cost,
      profit: d.profit,
      marginPct: d.margin_pct,
    };
  },
  remove: async (id: string): Promise<void> => {
    await api<{ message: string }>(`/api/trips/${id}`, { method: 'DELETE' });
  },
};

export const listTripDocuments = async (tripId: string): Promise<TripDocument[]> => {
  const data = await api<BackendTripDocument[]>(`/api/trips/${tripId}/documents`);
  return data.map(adaptDocument);
};

export const deleteTripDocument = async (tripId: string, docId: string): Promise<void> => {
  await api<void>(`/api/trips/${tripId}/documents/${docId}`, { method: 'DELETE' });
};
