import { api } from '@/lib/api';

/**
 * Drivers' stays in Russia — the 90-days-in-any-180 count. Mirrors
 * `app/routers/russia_stays.py`. Dates are Tashkent calendar days, `YYYY-MM-DD`.
 */

export interface StaySummary {
  in_russia: boolean;
  entered_on: string | null;
  day_of_stay: number | null;
  days_used: number;
  days_available: number;
  must_leave_by: string | null;
  /** 0 = leave today, negative = overstaying. */
  days_to_leave: number | null;
  overstay_days: number;
}

export interface RussiaStay {
  id: string;
  entered_on: string;
  left_on: string | null;
  source: 'auto' | 'manual' | string;
  trip_id: string | null;
  note: string | null;
}

export interface DriverStays {
  summary: StaySummary;
  stays: RussiaStay[];
}

export interface FleetStay {
  driver_id: string;
  driver_name: string;
  summary: StaySummary;
}

export interface StayInput {
  entered_on: string;
  left_on: string | null;
  note: string | null;
}

export type StayLevel = 'ok' | 'soon' | 'urgent' | 'over';

/** How loudly to show a stay: the same 15/3-day lines the reminders use. */
export function stayLevel(s: StaySummary): StayLevel {
  if (!s.in_russia || s.days_to_leave === null) return 'ok';
  if (s.overstay_days > 0 || s.days_to_leave < 0) return 'over';
  if (s.days_to_leave <= 3) return 'urgent';
  if (s.days_to_leave <= 15) return 'soon';
  return 'ok';
}

/** `2026-10-06` → `06.10.2026`, without a Date (which would shift the day west of UTC). */
export function dmy(day: string | null): string {
  return day ? day.split('-').reverse().join('.') : '—';
}

const base = (driverId: string) => `/api/drivers/${driverId}/russia-stays`;

export const russiaStaysApi = {
  fleet: () => api<FleetStay[]>('/api/russia-stays'),
  forDriver: (driverId: string) => api<DriverStays>(base(driverId)),
  add: (driverId: string, input: StayInput) =>
    api<RussiaStay>(base(driverId), { method: 'POST', body: input }),
  update: (driverId: string, stayId: string, input: StayInput) =>
    api<RussiaStay>(`${base(driverId)}/${stayId}`, { method: 'PATCH', body: input }),
  remove: (driverId: string, stayId: string) =>
    api<void>(`${base(driverId)}/${stayId}`, { method: 'DELETE' }),
};
