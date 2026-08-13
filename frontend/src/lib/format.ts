/**
 * Display formatting for fleet numbers.
 *
 * The API is metric and so'm-denominated throughout: fuel volumes are litres,
 * odometer/trip distances are kilometres, and every money field is UZS. Some
 * payload fields still carry imperial names from the original US-market schema
 * (`total_gallons`, `mpg`, `avg_price_per_gallon`) — those names lie about the
 * unit, so read them through the helpers here rather than trusting the key.
 */

/** Grouped with commas to match the rest of the app's tables. */
const GROUPED = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

const withDecimals = (digits: number) =>
  new Intl.NumberFormat('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

/** Money amount without a currency symbol — pair it with `t('common.currency')`. */
export function formatAmount(value: number, fractionDigits = 0): string {
  if (!Number.isFinite(value)) return '—';
  return fractionDigits > 0 ? withDecimals(fractionDigits).format(value) : GROUPED.format(value);
}

/** Fuel volume in litres. */
export function formatLiters(value: number, fractionDigits = 0): string {
  if (!Number.isFinite(value)) return '—';
  return fractionDigits > 0 ? withDecimals(fractionDigits).format(value) : GROUPED.format(value);
}

/** Distance in kilometres. */
export function formatKm(value: number, fractionDigits = 0): string {
  if (!Number.isFinite(value)) return '—';
  return fractionDigits > 0 ? withDecimals(fractionDigits).format(value) : GROUPED.format(value);
}

/**
 * Convert the API's km-per-litre efficiency into L/100km — the figure Uzbek
 * fleets actually budget against, and the same unit the Leakage page uses for
 * its fleet baseline. Returns null when there is nothing meaningful to show.
 */
export function toL100km(kmPerLiter: number): number | null {
  if (!Number.isFinite(kmPerLiter) || kmPerLiter <= 0) return null;
  return 100 / kmPerLiter;
}

/** L/100km rendered to one decimal, or an em dash when unavailable. */
export function formatL100km(kmPerLiter: number): string {
  const value = toL100km(kmPerLiter);
  return value === null ? '—' : withDecimals(1).format(value);
}
