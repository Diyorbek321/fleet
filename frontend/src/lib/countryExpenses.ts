import { ApiError, api, tokenStorage } from '@/lib/api';
import type { GeneratedReportFile } from '@/lib/reports';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

export type CountryCode = 'uz' | 'kz' | 'ru';

/**
 * Where an amount's exchange rate came from.
 *
 * `trip` is the rate the trip itself recorded (dollars handed over, tenge
 * received). `org` is the company's configured fallback. `mixed` only appears
 * on aggregates, where trips used different rates and the figure shown is the
 * spend-weighted one — a description of what happened, not a quote.
 */
export type RateSource = 'trip' | 'org' | 'mixed';

/**
 * A category from the driver's form, plus two the report adds: `fuel` (the GSM
 * table folded into the country the diesel was bought in) and `insurance`.
 */
export type CountryExpenseCategory =
  | 'fuel'
  | 'insurance'
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

/**
 * Field names stay snake_case, mirroring the API one-for-one — the same choice
 * `PeriodReport` makes, and for the same reason: a hand-written adapter over a
 * document-shaped payload is somewhere for the two shapes to drift apart.
 */
export interface CategoryLine {
  category: CountryExpenseCategory;
  /** In the block's own currency — never comparable across countries. */
  amount: number;
  /** null when no rate was available: nothing was converted, not nothing spent. */
  amount_usd: number | null;
  /** Only `fuel` carries litres. */
  liters: number | null;
}

export interface CountryBlock {
  country: CountryCode;
  currency: 'UZS' | 'KZT' | 'RUB';
  lines: CategoryLine[];
  total: number;
  total_usd: number | null;
  fuel_liters: number;
  rate: number | null;
  rate_source: RateSource | null;
}

/** Diesel bought on a card (DOHA, E1), which belongs to no single country. */
export interface CardFuel {
  column: 'doha' | 'e1card';
  liters: number;
  amount: number;
}

export interface CountryExpenseTrip {
  trip_id: string;
  reference: string;
  truck_id: string | null;
  truck_name: string | null;
  plate_number: string | null;
  driver_name: string | null;
  trip_date: string | null;
  route: string | null;
  distance_km: number | null;
  report_status: 'draft' | 'submitted' | null;
  countries: CountryBlock[];
  cards: CardFuel[];
  total_usd: number | null;
  /** A country on this trip had spending but no rate, so the USD total is short. */
  usd_partial: boolean;
}

export interface CountryExpenseReport {
  organization: string;
  start: string;
  end: string;
  generated_at: string;
  truck_id: string | null;
  trips: CountryExpenseTrip[];
  /** The same three countries, rolled up over every trip in the range. */
  countries: CountryBlock[];
  cards: CardFuel[];
  total_usd: number | null;
  usd_partial: boolean;
  /** Countries with spending but no usable rate — fixable in Settings. */
  countries_missing_rate: CountryCode[];
}

export interface CountryExpenseQuery {
  from: string;
  to: string;
  truckId?: string;
}

function toParams({ from, to, truckId }: CountryExpenseQuery): string {
  const params = new URLSearchParams({ from, to });
  if (truckId) params.set('truck_id', truckId);
  return params.toString();
}

export const countryExpensesApi = {
  get: (query: CountryExpenseQuery) =>
    api<CountryExpenseReport>(`/api/reports/country-expenses?${toParams(query)}`),

  /** The same breakdown as a spreadsheet, with the server's own filename. */
  xlsx: async (query: CountryExpenseQuery): Promise<GeneratedReportFile> => {
    const token = tokenStorage.getAccess();
    const res = await fetch(`${BASE_URL}/api/reports/country-expenses.xlsx?${toParams(query)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, detail);
    }
    const disposition = res.headers.get('Content-Disposition') ?? '';
    const filename = disposition.match(/filename="?([^"]+)"?/)?.[1] ?? 'reys-xarajatlari.xlsx';
    return { filename, blob: await res.blob() };
  },
};

/** The order the three countries are shown in — the order the money is spent. */
export const COUNTRY_ORDER: readonly CountryCode[] = ['uz', 'kz', 'ru'];

/**
 * A named range the user can pick. Dates are resolved at click time rather than
 * stored, so a tab left open overnight does not keep reporting yesterday's
 * "this month".
 */
export interface RangeChoice {
  key: string;
  labelKey: string;
  resolve: (today: Date) => { from: string; to: string };
}

const iso = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

export const RANGE_CHOICES: readonly RangeChoice[] = [
  {
    key: 'thisMonth',
    labelKey: 'countryExpenses.range.thisMonth',
    resolve: (today) => ({ from: iso(new Date(today.getFullYear(), today.getMonth(), 1)), to: iso(today) }),
  },
  {
    key: 'lastMonth',
    labelKey: 'countryExpenses.range.lastMonth',
    resolve: (today) => ({
      from: iso(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
      to: iso(new Date(today.getFullYear(), today.getMonth(), 0)),
    }),
  },
  {
    key: 'last90',
    labelKey: 'countryExpenses.range.last90',
    resolve: (today) => {
      const from = new Date(today);
      from.setDate(from.getDate() - 89);
      return { from: iso(from), to: iso(today) };
    },
  },
  {
    key: 'thisYear',
    labelKey: 'countryExpenses.range.thisYear',
    resolve: (today) => ({ from: iso(new Date(today.getFullYear(), 0, 1)), to: iso(today) }),
  },
];
