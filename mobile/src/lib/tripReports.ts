import AsyncStorage from '@react-native-async-storage/async-storage';

import { apiFetch } from './api';

export type TripReportStatus = 'draft' | 'submitted';
export type TripReportCountry = 'kz' | 'ru' | 'uz';
export type TripReportExpenseCategory =
  | 'platon'
  | 'food'
  | 'traffic_police'
  | 'adblue'
  | 'fine'
  | 'spare_parts'
  | 'repair'
  | 'refund'
  | 'parking'
  | 'phone'
  | 'transport'
  | 'shower'
  | 'groceries'
  | 'parking_paperwork'
  | 'taxi'
  | 'carwash';

export interface TripFuelRow {
  row_no: number;
  kz_liters: number | null;
  kz_amount: number | null;
  rf_liters: number | null;
  rf_amount: number | null;
  doha_liters: number | null;
  doha_amount: number | null;
  e1card_liters: number | null;
  e1card_amount: number | null;
}

export interface TripCountryExpenseLine {
  country: TripReportCountry;
  category: TripReportExpenseCategory;
  amount: number;
}

export interface TripReportTotals {
  fuel_by_column: Record<'kz' | 'rf' | 'doha' | 'e1card', { liters: number; amount: number }>;
  fuel_liters_total: number;
  fuel_amount_total: number;
  country_totals: Record<TripReportCountry, number>;
  currency_balances: Record<'usd' | 'rub' | 'kzt' | 'uzs', number>;
}

export interface TripExpenseReport {
  id: string;
  trip_id: string;
  status: TripReportStatus;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;

  plate_number: string | null;
  driver_name: string | null;
  report_date: string | null;
  odometer_out: number | null;
  odometer_in: number | null;
  fuel_at_garage: number | null;
  route_text: string | null;
  exchange_rate_note: string | null;

  money_usd: number | null;
  money_rub: number | null;
  money_kzt: number | null;
  money_uzs: number | null;
  usd_to_kzt_given: number | null;
  usd_to_kzt_received: number | null;
  usd_to_rub_given: number | null;
  usd_to_rub_received: number | null;

  border_departure_at: string | null;
  border_arrival_at: string | null;
  electronic_pass_note: string | null;
  electronic_queue_note: string | null;

  insurance_rf: number | null;
  insurance_kz: number | null;
  dollar_return: number | null;
  driver_comment: string | null;

  fuel_rows: TripFuelRow[];
  country_expenses: TripCountryExpenseLine[];
  totals: TripReportTotals;
}

/** Everything the form can save — same shape as the report minus server-owned fields. */
export type TripReportInput = Partial<
  Omit<
    TripExpenseReport,
    'id' | 'trip_id' | 'status' | 'submitted_at' | 'created_at' | 'updated_at' | 'totals'
  >
>;

export const tripReportsApi = {
  get: (tripId: string) => apiFetch<TripExpenseReport | null>(`/api/me/trips/${tripId}/report`),
  save: (tripId: string, data: TripReportInput) =>
    apiFetch<TripExpenseReport>(`/api/me/trips/${tripId}/report`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  submit: (tripId: string) =>
    apiFetch<TripExpenseReport>(`/api/me/trips/${tripId}/report/submit`, { method: 'POST' }),
};

const DRAFT_KEY_PREFIX = 'tripReportDraft:';

/** What the driver was trying to do the last time a network call failed —
 *  used to pick up the retry where it left off instead of just re-saving. */
export type TripReportPendingAction = 'save' | 'submit' | null;

export interface TripReportDraft<T> {
  savedAt: string;
  pendingAction: TripReportPendingAction;
  data: T;
}

/**
 * On-device draft persistence for the trip report form, keyed by trip id.
 *
 * This form is filled out at border crossings — exactly where connectivity
 * is worst — so the form state must survive an app kill or a failed
 * save/submit without depending on the network. Generic over `T` so the
 * component owns the shape of its own draft (form field state), while this
 * module owns nothing but the storage mechanics. All operations are best
 * effort: a local storage failure must never surface as a driver-facing
 * error on top of whatever network problem already prompted the save.
 */
export async function loadTripReportDraft<T>(tripId: string): Promise<TripReportDraft<T> | null> {
  try {
    const raw = await AsyncStorage.getItem(DRAFT_KEY_PREFIX + tripId);
    if (!raw) return null;
    return JSON.parse(raw) as TripReportDraft<T>;
  } catch {
    return null;
  }
}

export async function saveTripReportDraft<T>(
  tripId: string,
  data: T,
  pendingAction: TripReportPendingAction = null,
): Promise<void> {
  try {
    const draft: TripReportDraft<T> = { savedAt: new Date().toISOString(), pendingAction, data };
    await AsyncStorage.setItem(DRAFT_KEY_PREFIX + tripId, JSON.stringify(draft));
  } catch {
    // Best effort — nothing else to fall back to if local storage itself is unavailable.
  }
}

export async function clearTripReportDraft(tripId: string): Promise<void> {
  try {
    await AsyncStorage.removeItem(DRAFT_KEY_PREFIX + tripId);
  } catch {
    // ignore
  }
}
