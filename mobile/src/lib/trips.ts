import { apiFetch } from './api';

export type TripStatus =
  | 'draft'
  | 'planned'
  | 'loading'
  | 'en_route'
  | 'at_border'
  | 'delivered'
  | 'cancelled';

export interface Trip {
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

export interface AdvanceInput {
  to_status: TripStatus;
  note?: string | null;
  latitude?: number | null;
  longitude?: number | null;
}

/** The next status a driver can move a trip to (linear flow; null = terminal). */
export const NEXT_STATUS: Record<TripStatus, TripStatus | null> = {
  draft: 'planned',
  planned: 'loading',
  loading: 'en_route',
  en_route: 'at_border',
  at_border: 'delivered',
  delivered: null,
  cancelled: null,
};

export const tripsApi = {
  mine: () => apiFetch<Trip[]>('/api/me/trips'),
  advance: (tripId: string, data: AdvanceInput) =>
    apiFetch<Trip>(`/api/me/trips/${tripId}/advance`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};
