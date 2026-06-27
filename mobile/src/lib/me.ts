import { apiFetch } from './api';

export interface DriverProfile {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  license_number: string;
  license_expiry: string | null;
  status: string;
  photo_url: string | null;
}

export interface AssignedTruck {
  id: string;
  name: string;
  plate_number: string;
  model: string | null;
  status: string;
  fuel_level: number;
  mileage: number;
}

export interface Shift {
  id: string;
  driver_id: string;
  truck_id: string | null;
  status: 'active' | 'ended';
  started_at: string;
  ended_at: string | null;
  start_mileage: number | null;
  end_mileage: number | null;
}

export interface SafetyScore {
  id: string;
  score: number;
  speeding_events: number;
  harsh_braking: number;
  harsh_acceleration: number;
  idle_time_minutes: number;
  period_start: string;
  period_end: string;
  calculated_at: string;
}

export interface FuelLog {
  id: string;
  truck_id: string;
  liters: number;
  cost_per_liter: number;
  total_cost: number;
  mileage_at_fill: number | null;
  fuel_station: string | null;
  filled_at: string;
  created_at: string;
}

export interface MaintenanceRecord {
  id: string;
  truck_id: string;
  service_type: string;
  description: string | null;
  cost: number | null;
  mileage_at_service: number | null;
  performed_by: string | null;
  performed_at: string;
  notes: string | null;
  created_at: string;
}

export interface NewFuelLog {
  liters: number;
  cost_per_liter: number;
  mileage_at_fill?: number | null;
  fuel_station?: string | null;
}

export type ExpenseCategory =
  | 'food'
  | 'toll'
  | 'parking'
  | 'fine'
  | 'repair'
  | 'lodging'
  | 'customs'
  | 'other';

export interface Expense {
  id: string;
  driver_id: string;
  truck_id: string | null;
  category: ExpenseCategory;
  amount: number;
  note: string | null;
  receipt_url: string | null;
  spent_at: string;
  created_at: string;
}

export interface NewExpense {
  category: ExpenseCategory;
  amount: number;
  note?: string | null;
  receipt_url?: string | null;
  spent_at?: string | null;
}

export interface LocationPing {
  latitude: number;
  longitude: number;
  speed?: number;
  heading?: number | null;
}

/** Suggested document categories shown in the driver UI (backend accepts any). */
export type TripDocumentCategory = 'cmr' | 'invoice' | 'customs' | 'other';

/** A photo document uploaded against a specific trip. `url` is ready for <Image>. */
export interface TripDocument {
  id: string;
  trip_id: string;
  category: string | null;
  caption: string | null;
  content_type: string;
  size_bytes: number;
  url: string;
  uploaded_at: string;
  driver_name: string | null;
}

/** The shape of an image picked via expo-image-picker that we upload. */
export interface TripDocumentAsset {
  uri: string;
  mimeType?: string;
  fileName?: string;
}

/** Infer an image MIME type from the picker's mimeType, falling back to the URI extension. */
function inferImageType(uri: string, mimeType?: string): string {
  if (mimeType) return mimeType;
  const ext = uri.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'png':
      return 'image/png';
    case 'heic':
      return 'image/heic';
    case 'heif':
      return 'image/heif';
    case 'webp':
      return 'image/webp';
    default:
      return 'image/jpeg';
  }
}

/** Typed client for the driver self-scoped endpoints. */
export const meApi = {
  profile: () => apiFetch<DriverProfile>('/api/me/profile'),
  assignment: () => apiFetch<AssignedTruck | null>('/api/me/assignment'),
  safetyScore: () => apiFetch<SafetyScore | null>('/api/me/safety-score'),

  currentShift: () => apiFetch<Shift | null>('/api/me/shifts/current'),
  startShift: (start_mileage?: number | null) =>
    apiFetch<Shift>('/api/me/shifts/start', {
      method: 'POST',
      body: JSON.stringify({ start_mileage: start_mileage ?? null }),
    }),
  endShift: (end_mileage?: number | null) =>
    apiFetch<Shift>('/api/me/shifts/end', {
      method: 'POST',
      body: JSON.stringify({ end_mileage: end_mileage ?? null }),
    }),

  fuelLogs: () => apiFetch<FuelLog[]>('/api/me/fuel-logs'),
  addFuelLog: (data: NewFuelLog) =>
    apiFetch<FuelLog>('/api/me/fuel-logs', { method: 'POST', body: JSON.stringify(data) }),

  expenses: (month?: string) =>
    apiFetch<Expense[]>(`/api/me/expenses${month ? `?month=${month}` : ''}`),
  addExpense: (data: NewExpense) =>
    apiFetch<Expense>('/api/me/expenses', { method: 'POST', body: JSON.stringify(data) }),
  deleteExpense: (id: string) =>
    apiFetch(`/api/me/expenses/${id}`, { method: 'DELETE' }),

  maintenance: () => apiFetch<MaintenanceRecord[]>('/api/me/maintenance'),
  reportIssue: (data: { title: string; description?: string | null }) =>
    apiFetch('/api/me/maintenance-requests', { method: 'POST', body: JSON.stringify(data) }),

  pingLocation: (data: LocationPing) =>
    apiFetch('/api/me/location', { method: 'POST', body: JSON.stringify(data) }),

  /** Newest-first photo documents the driver has uploaded for one of their trips. */
  listTripDocuments: (tripId: string) =>
    apiFetch<TripDocument[]>(`/api/me/trips/${tripId}/documents`),

  /** Upload one image as a trip document via multipart/form-data. */
  uploadTripDocument: (
    tripId: string,
    asset: TripDocumentAsset,
    opts?: { category?: string; caption?: string },
  ) => {
    const form = new FormData();
    const name = asset.fileName ?? 'photo.jpg';
    const type = inferImageType(asset.uri, asset.mimeType);
    // RN's multipart file shape ({ uri, name, type }) isn't a web Blob — localized cast.
    form.append('file', { uri: asset.uri, name, type } as unknown as Blob);
    if (opts?.category) form.append('category', opts.category);
    if (opts?.caption) form.append('caption', opts.caption);
    return apiFetch<TripDocument>(`/api/me/trips/${tripId}/documents`, {
      method: 'POST',
      body: form,
    });
  },
};
