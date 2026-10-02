import type { Truck } from '@/types';

/**
 * A rig's insurance, one policy per country it crosses. Mirrors
 * `INSURANCE_POLICIES` in `app/models/trucks.py`: the Uzbek policy lives in
 * the original `insuranceExpiry` field, Kazakhstan and Russia beside it.
 */
export type InsuranceCountry = 'uz' | 'kz' | 'rf';

export const INSURANCE_POLICIES = [
  { country: 'uz', field: 'insuranceExpiry' },
  { country: 'kz', field: 'insuranceExpiryKz' },
  { country: 'rf', field: 'insuranceExpiryRf' },
] as const satisfies readonly { country: InsuranceCountry; field: keyof Truck }[];

export type InsuranceField = (typeof INSURANCE_POLICIES)[number]['field'];

/** Same thresholds the reminders use: a month out, the last week, past it. */
export const SOON_DAYS = 30;
export const URGENT_DAYS = 7;

export type InsuranceState = 'missing' | 'expired' | 'urgent' | 'soon' | 'ok';

/** Today as a calendar date in the viewer's timezone, `YYYY-MM-DD`. */
export function localToday(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** Whole days from `today` to `expiry`; negative once it has lapsed.
 *  Both are calendar dates, so the count never drifts by a timezone. */
export function daysLeft(expiry: string, today: string = localToday()): number {
  const toUtc = (iso: string) => {
    const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((toUtc(expiry) - toUtc(today)) / 86_400_000);
}

export function insuranceState(expiry: string | null | undefined, today: string = localToday()): InsuranceState {
  if (!expiry) return 'missing';
  const days = daysLeft(expiry, today);
  if (days < 0) return 'expired';
  if (days <= URGENT_DAYS) return 'urgent';
  if (days <= SOON_DAYS) return 'soon';
  return 'ok';
}

/** Days to the truck's nearest-lapsing policy, or null when none is entered.
 *  What "most urgent first" sorts by. */
export function nearestDaysLeft(truck: Truck, today: string = localToday()): number | null {
  const days = INSURANCE_POLICIES.map(({ field }) => truck[field])
    .filter((v): v is string => !!v)
    .map((v) => daysLeft(v, today));
  return days.length ? Math.min(...days) : null;
}

export interface InsuranceSummary {
  expired: number;
  soon: number;
  missing: number;
}

/** Counts policies, not trucks: one rig with two lapsed policies is two
 *  things to renew. */
export function summarize(trucks: Truck[], today: string = localToday()): InsuranceSummary {
  const summary: InsuranceSummary = { expired: 0, soon: 0, missing: 0 };
  for (const truck of trucks) {
    for (const { field } of INSURANCE_POLICIES) {
      const state = insuranceState(truck[field], today);
      if (state === 'expired') summary.expired += 1;
      else if (state === 'urgent' || state === 'soon') summary.soon += 1;
      else if (state === 'missing') summary.missing += 1;
    }
  }
  return summary;
}
