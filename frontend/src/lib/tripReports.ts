import { api } from '@/lib/api';

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
  rowNo: number;
  kzLiters: number | null;
  kzAmount: number | null;
  rfLiters: number | null;
  rfAmount: number | null;
  dohaLiters: number | null;
  dohaAmount: number | null;
  e1cardLiters: number | null;
  e1cardAmount: number | null;
}

export interface TripCountryExpenseLine {
  country: TripReportCountry;
  category: TripReportExpenseCategory;
  amount: number;
}

export interface FuelColumnTotals {
  liters: number;
  amount: number;
}

export interface TripReportTotals {
  fuelByColumn: Record<'kz' | 'rf' | 'doha' | 'e1card', FuelColumnTotals>;
  fuelLitersTotal: number;
  fuelAmountTotal: number;
  countryTotals: Record<TripReportCountry, number>;
  currencyBalances: Record<'usd' | 'rub' | 'kzt' | 'uzs', number>;
}

export interface TripExpenseReport {
  id: string;
  tripId: string;
  status: TripReportStatus;
  submittedAt: string | null;
  createdAt: string;
  updatedAt: string;

  plateNumber: string | null;
  driverName: string | null;
  reportDate: string | null;
  odometerOut: number | null;
  odometerIn: number | null;
  fuelAtGarage: number | null;
  routeText: string | null;
  exchangeRateNote: string | null;

  moneyUsd: number | null;
  moneyRub: number | null;
  moneyKzt: number | null;
  moneyUzs: number | null;
  usdToKztGiven: number | null;
  usdToKztReceived: number | null;
  usdToRubGiven: number | null;
  usdToRubReceived: number | null;

  borderDepartureAt: string | null;
  borderArrivalAt: string | null;
  electronicPassNote: string | null;
  electronicQueueNote: string | null;

  insuranceRf: number | null;
  insuranceKz: number | null;
  dollarReturn: number | null;
  driverComment: string | null;

  fuelRows: TripFuelRow[];
  countryExpenses: TripCountryExpenseLine[];
  totals: TripReportTotals;
}

interface BackendFuelRow {
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

interface BackendCountryExpenseLine {
  country: TripReportCountry;
  category: TripReportExpenseCategory;
  amount: number;
}

interface BackendTotals {
  fuel_by_column: Record<string, { liters: number; amount: number }>;
  fuel_liters_total: number;
  fuel_amount_total: number;
  country_totals: Record<string, number>;
  currency_balances: Record<string, number>;
}

interface BackendTripExpenseReport {
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
  fuel_rows: BackendFuelRow[];
  country_expenses: BackendCountryExpenseLine[];
  totals: BackendTotals;
}

function adaptFuelRow(r: BackendFuelRow): TripFuelRow {
  return {
    rowNo: r.row_no,
    kzLiters: r.kz_liters,
    kzAmount: r.kz_amount,
    rfLiters: r.rf_liters,
    rfAmount: r.rf_amount,
    dohaLiters: r.doha_liters,
    dohaAmount: r.doha_amount,
    e1cardLiters: r.e1card_liters,
    e1cardAmount: r.e1card_amount,
  };
}

function adaptTotals(t: BackendTotals): TripReportTotals {
  return {
    fuelByColumn: t.fuel_by_column as TripReportTotals['fuelByColumn'],
    fuelLitersTotal: t.fuel_liters_total,
    fuelAmountTotal: t.fuel_amount_total,
    countryTotals: t.country_totals as TripReportTotals['countryTotals'],
    currencyBalances: t.currency_balances as TripReportTotals['currencyBalances'],
  };
}

function adaptReport(r: BackendTripExpenseReport): TripExpenseReport {
  return {
    id: r.id,
    tripId: r.trip_id,
    status: r.status,
    submittedAt: r.submitted_at,
    createdAt: r.created_at,
    updatedAt: r.updated_at,
    plateNumber: r.plate_number,
    driverName: r.driver_name,
    reportDate: r.report_date,
    odometerOut: r.odometer_out,
    odometerIn: r.odometer_in,
    fuelAtGarage: r.fuel_at_garage,
    routeText: r.route_text,
    exchangeRateNote: r.exchange_rate_note,
    moneyUsd: r.money_usd,
    moneyRub: r.money_rub,
    moneyKzt: r.money_kzt,
    moneyUzs: r.money_uzs,
    usdToKztGiven: r.usd_to_kzt_given,
    usdToKztReceived: r.usd_to_kzt_received,
    usdToRubGiven: r.usd_to_rub_given,
    usdToRubReceived: r.usd_to_rub_received,
    borderDepartureAt: r.border_departure_at,
    borderArrivalAt: r.border_arrival_at,
    electronicPassNote: r.electronic_pass_note,
    electronicQueueNote: r.electronic_queue_note,
    insuranceRf: r.insurance_rf,
    insuranceKz: r.insurance_kz,
    dollarReturn: r.dollar_return,
    driverComment: r.driver_comment,
    fuelRows: r.fuel_rows.map(adaptFuelRow),
    countryExpenses: r.country_expenses,
    totals: adaptTotals(r.totals),
  };
}

export const tripReportsApi = {
  get: async (tripId: string): Promise<TripExpenseReport | null> => {
    const data = await api<BackendTripExpenseReport | null>(`/api/trips/${tripId}/report`);
    return data ? adaptReport(data) : null;
  },
};
