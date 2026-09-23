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
  current_stage: TripStage | null;
  current_stage_place: StagePlace | null;
  loaded_at: string | null;
  eta_customs: string | null;
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
  /** Optional: when a stage is given the server derives the status from it. */
  to_status?: TripStatus;
  stage?: TripStage;
  stage_place?: StagePlace;
  note?: string | null;
  latitude?: number | null;
  longitude?: number | null;
}

/**
 * The checkpoint the driver actually reports, finer than `TripStatus`.
 *
 * `TripStatus` stays the coarse lifecycle every report and alert is built on;
 * this is what the cargo owner reads. The two are not parallel lists — the
 * server derives the status from the stage, so a driver only ever picks one.
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

/** Where the stage happened: a country, or — at a border — the crossing itself. */
export type StagePlace = 'uz' | 'kz' | 'ru' | 'uz_kz' | 'kz_ru';

/** Display order: the order a UZ↔RU run normally goes through. */
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

const COUNTRIES: StagePlace[] = ['uz', 'kz', 'ru'];
const CROSSINGS: StagePlace[] = ['uz_kz', 'kz_ru'];

/**
 * Which places a stage can carry.
 *
 * A border stage names the crossing ("УЗБ–КЗ"), not a single country: on a
 * Tashkent–Tobolsk run the truck reaches a border twice, and only the crossing
 * tells the two apart — for the customer's message and for the ETA.
 */
export function placesFor(stage: TripStage): StagePlace[] {
  return stage === 'arrived_border' || stage === 'crossed_border' ? CROSSINGS : COUNTRIES;
}

/**
 * Stages ordered with the likely next one first.
 *
 * Deliberately a suggestion, not a rule: real runs skip customs, reverse
 * direction, or cross a border twice, and a driver who cannot report what
 * actually happened stops reporting at all. The server accepts any stage.
 */
export function suggestedStages(current: TripStage | null): TripStage[] {
  if (!current) return TRIP_STAGES;
  const i = TRIP_STAGES.indexOf(current);
  if (i < 0) return TRIP_STAGES;
  // A border repeats, so after crossing one the next likely step is the next
  // border, not the stage that merely follows it in the list.
  const rest = TRIP_STAGES.slice(i + 1);
  const wrap = TRIP_STAGES.slice(0, i + 1);
  return [...rest, ...wrap];
}

export const tripsApi = {
  mine: () => apiFetch<Trip[]>('/api/me/trips'),
  advance: (tripId: string, data: AdvanceInput) =>
    apiFetch<Trip>(`/api/me/trips/${tripId}/advance`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};
