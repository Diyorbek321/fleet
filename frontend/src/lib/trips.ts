import { api } from '@/lib/api';

export type TripStatus =
  | 'draft'
  | 'planned'
  | 'loading'
  | 'en_route'
  | 'at_border'
  | 'delivered'
  | 'cancelled';

/**
 * The checkpoint a driver reports, finer than `TripStatus`.
 *
 * The status stays the coarse lifecycle every report and alert is built on;
 * this is the line the cargo owner reads. The server derives one from the
 * other, so they never disagree.
 */
export type TripStage =
  | 'arrived_loading'
  | 'loaded_waiting_docs'
  | 'docs_received_en_route'
  | 'arrived_border'
  | 'crossed_border'
  | 'arrived_customs'
  | 'left_customs'
  | 'arrived_unloading'
  | 'unloaded';

/** Where a stage happened: a country, or — at a border — the crossing itself. */
export type StagePlace = 'uz' | 'kz' | 'ru' | 'uz_kz' | 'kz_ru';

/** The checkpoints in the order a run passes them. */
export const TRIP_STAGES: TripStage[] = [
  'arrived_loading',
  'loaded_waiting_docs',
  'docs_received_en_route',
  'arrived_border',
  'crossed_border',
  'arrived_customs',
  'left_customs',
  'arrived_unloading',
  'unloaded',
];

/** Mirrors the server's `places_for_stage`: a border stage names the
 *  crossing, every other stage one country. */
export function placesForStage(stage: TripStage): StagePlace[] {
  return stage === 'arrived_border' || stage === 'crossed_border'
    ? ['uz_kz', 'kz_ru']
    : ['uz', 'kz', 'ru'];
}

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
  currentStage: TripStage | null;
  currentStagePlace: StagePlace | null;
  loadedAt: string | null;
  /** Expected arrival at customs, ISO date, or null when not estimable. */
  etaCustoms: string | null;
  /** How that date was reached: measured from past trips, or modelled. */
  etaBasis: 'history' | 'model' | null;
  shipper: string | null;
  consignee: string | null;
  originName: string | null;
  destinationName: string | null;
  borderCrossing: string | null;
  loadingAddress: string | null;
  loadingContact: string | null;
  customsPoint: string | null;
  unloadingAddress: string | null;
  declarantContact: string | null;
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
  current_stage: TripStage | null;
  current_stage_place: StagePlace | null;
  loaded_at: string | null;
  eta_customs: string | null;
  eta_basis: 'history' | 'model' | null;
  shipper: string | null;
  consignee: string | null;
  origin_name: string | null;
  destination_name: string | null;
  border_crossing?: string | null;
  loading_address?: string | null;
  loading_contact?: string | null;
  customs_point?: string | null;
  unloading_address?: string | null;
  declarant_contact?: string | null;
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
    currentStage: t.current_stage ?? null,
    currentStagePlace: t.current_stage_place ?? null,
    loadedAt: t.loaded_at ?? null,
    etaCustoms: t.eta_customs ?? null,
    etaBasis: t.eta_basis ?? null,
    shipper: t.shipper,
    consignee: t.consignee,
    originName: t.origin_name,
    destinationName: t.destination_name,
    borderCrossing: t.border_crossing ?? null,
    loadingAddress: t.loading_address ?? null,
    loadingContact: t.loading_contact ?? null,
    customsPoint: t.customs_point ?? null,
    unloadingAddress: t.unloading_address ?? null,
    declarantContact: t.declarant_contact ?? null,
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

/** Everything the trip form collects — the lines of the order sheet sent to
 *  the driver. `null` means "blank": dropped on create, sent on an edit so
 *  that emptying a field actually clears it. */
export interface TripCreateInput {
  truckId?: string | null;
  driverId?: string | null;
  borderCrossing?: string | null;
  shipper?: string | null;
  loadingAddress?: string | null;
  loadingContact?: string | null;
  consignee?: string | null;
  customsPoint?: string | null;
  unloadingAddress?: string | null;
  declarantContact?: string | null;
  originName?: string | null;
  destinationName?: string | null;
  cargoDescription?: string | null;
  cargoWeightKg?: number | null;
  isReefer?: boolean;
  rate?: number;
  currency?: string;
  plannedDistanceKm?: number | null;
  /** Loading date, ISO. */
  scheduledStart?: string | null;
  notes?: string | null;
}

const WIRE_NAMES: Record<keyof TripCreateInput, string> = {
  truckId: 'truck_id',
  driverId: 'driver_id',
  borderCrossing: 'border_crossing',
  shipper: 'shipper',
  loadingAddress: 'loading_address',
  loadingContact: 'loading_contact',
  consignee: 'consignee',
  customsPoint: 'customs_point',
  unloadingAddress: 'unloading_address',
  declarantContact: 'declarant_contact',
  originName: 'origin_name',
  destinationName: 'destination_name',
  cargoDescription: 'cargo_description',
  cargoWeightKg: 'cargo_weight_kg',
  isReefer: 'is_reefer',
  rate: 'rate',
  currency: 'currency',
  plannedDistanceKm: 'planned_distance_km',
  scheduledStart: 'scheduled_start',
  notes: 'notes',
};

/** Create: only what was filled in. Update: every key the caller passed,
 *  blanks as null. */
export function toBody(input: TripCreateInput, mode: 'create' | 'update'): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const [key, wire] of Object.entries(WIRE_NAMES) as [keyof TripCreateInput, string][]) {
    const value = input[key];
    if (value === undefined) continue;
    const blank = value === null || value === '';
    if (blank && mode === 'create') continue;
    body[wire] = blank ? null : value;
  }
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
    const data = await api<BackendTripDetails>('/api/trips', { method: 'POST', body: toBody(input, 'create') });
    return adaptDetails(data);
  },
  update: async (id: string, input: TripCreateInput): Promise<TripDetails> => {
    const data = await api<BackendTripDetails>(`/api/trips/${id}`, { method: 'PUT', body: toBody(input, 'update') });
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
  /** Report a checkpoint on the driver's behalf — same timeline entry, and
   *  the same status derived from it, as when the driver taps it. */
  advanceStage: async (
    id: string,
    stage: TripStage,
    place: StagePlace | null,
    note?: string,
  ): Promise<TripDetails> => {
    const data = await api<BackendTripDetails>(`/api/trips/${id}/advance`, {
      method: 'POST',
      body: { stage, stage_place: place, note: note || undefined },
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

// ── Cargo-owner Telegram subscriptions ───────────────────────────────────

export interface TripSubscription {
  id: string;
  tripId: string;
  contactName: string | null;
  contactPhone: string | null;
  dailyEnabled: boolean;
  eventEnabled: boolean;
  activated: boolean;
  activatedAt: string | null;
  deepLink: string;
}

interface BackendTripSubscription {
  id: string;
  trip_id: string;
  contact_name: string | null;
  contact_phone: string | null;
  daily_enabled: boolean;
  event_enabled: boolean;
  activated: boolean;
  activated_at: string | null;
  deep_link: string;
}

function adaptSubscription(s: BackendTripSubscription): TripSubscription {
  return {
    id: s.id,
    tripId: s.trip_id,
    contactName: s.contact_name,
    contactPhone: s.contact_phone,
    dailyEnabled: s.daily_enabled,
    eventEnabled: s.event_enabled,
    activated: s.activated,
    activatedAt: s.activated_at,
    deepLink: s.deep_link,
  };
}

export const tripSubscriptionsApi = {
  list: async (tripId: string): Promise<TripSubscription[]> => {
    const data = await api<BackendTripSubscription[]>(
      `/api/trip-subscriptions?trip_id=${encodeURIComponent(tripId)}`,
    );
    return data.map(adaptSubscription);
  },
  create: async (
    tripId: string,
    contact: { contactName?: string | null; contactPhone?: string | null } = {},
  ): Promise<TripSubscription> => {
    const data = await api<BackendTripSubscription>('/api/trip-subscriptions', {
      method: 'POST',
      body: {
        trip_id: tripId,
        contact_name: contact.contactName ?? null,
        contact_phone: contact.contactPhone ?? null,
      },
    });
    return adaptSubscription(data);
  },
  remove: async (id: string): Promise<void> => {
    await api<void>(`/api/trip-subscriptions/${id}`, { method: 'DELETE' });
  },
};

export const listTripDocuments = async (tripId: string): Promise<TripDocument[]> => {
  const data = await api<BackendTripDocument[]>(`/api/trips/${tripId}/documents`);
  return data.map(adaptDocument);
};

export const deleteTripDocument = async (tripId: string, docId: string): Promise<void> => {
  await api<void>(`/api/trips/${tripId}/documents/${docId}`, { method: 'DELETE' });
};
