/**
 * The driver's own days in Russia — 90 in any 180. Mirrors `StaySummaryOut`
 * in backend/app/routers/russia_stays.py; the server does the counting.
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

export type StayLevel = 'ok' | 'soon' | 'urgent' | 'over';

/** The same 15/3-day lines the push reminders use. */
export function stayLevel(s: StaySummary): StayLevel {
  if (!s.in_russia || s.days_to_leave === null) return 'ok';
  if (s.overstay_days > 0 || s.days_to_leave < 0) return 'over';
  if (s.days_to_leave <= 3) return 'urgent';
  if (s.days_to_leave <= 15) return 'soon';
  return 'ok';
}

/** `2026-10-06` → `06.10.2026`. */
export function dmy(day: string | null): string {
  return day ? day.split('-').reverse().join('.') : '—';
}
