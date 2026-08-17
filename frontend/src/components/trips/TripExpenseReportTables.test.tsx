/**
 * The digitized "yo'l varaqasi" — the sheet a dispatcher reconciles a driver's
 * cash against. Totals are computed on the server (covered by
 * backend/tests/test_trip_reports.py); what can go wrong *here* is placement:
 * a nine-cell fuel row and three near-identical country tables are exactly the
 * shape where a copy-paste slip shifts money one column left and nobody
 * notices, because every cell still holds a plausible number.
 */
import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import type { TripExpenseReport } from '@/lib/tripReports';

import { TripExpenseReportTables } from './TripExpenseReportTables';

const n = (v: number) => v.toLocaleString();

const report: TripExpenseReport = {
  id: 'r-1',
  tripId: 't-1',
  status: 'submitted',
  submittedAt: '2026-08-01T10:00:00Z',
  createdAt: '2026-07-20T10:00:00Z',
  updatedAt: '2026-08-01T10:00:00Z',

  plateNumber: '01A123BC',
  driverName: 'Anvar',
  reportDate: '2026-07-20',
  odometerOut: 412_300,
  odometerIn: 415_900,
  fuelAtGarage: 180,
  routeText: 'Tashkent → Moscow',
  exchangeRateNote: '1$ = 12 600',

  moneyUsd: 1500,
  moneyRub: 20_000,
  moneyKzt: 90_000,
  moneyUzs: 3_000_000,
  usdToKztGiven: 300,
  usdToKztReceived: 148_000,
  usdToRubGiven: 200,
  usdToRubReceived: 18_400,

  borderDepartureAt: '2026-07-21T06:00:00Z',
  borderArrivalAt: '2026-07-21T14:00:00Z',
  electronicPassNote: 'EP-77',
  electronicQueueNote: 'Q-12',

  insuranceRf: 45_000,
  insuranceKz: 22_000,
  dollarReturn: 120,
  driverComment: 'Queue at Sagarchin was 9 hours',

  // Every one of the eight fuel figures is distinct so a mis-ordered cell
  // cannot accidentally match its neighbour.
  fuelRows: [
    {
      rowNo: 1,
      kzLiters: 111,
      kzAmount: 222,
      rfLiters: 333,
      rfAmount: 444,
      dohaLiters: 555,
      dohaAmount: 666,
      e1cardLiters: 777,
      e1cardAmount: 888,
    },
  ],
  countryExpenses: [
    { country: 'kz', category: 'platon', amount: 41_000 },
    { country: 'kz', category: 'food', amount: 12_000 },
    { country: 'ru', category: 'platon', amount: 73_000 },
    { country: 'uz', category: 'groceries', amount: 250_000 },
  ],
  totals: {
    fuelByColumn: {
      kz: { liters: 111, amount: 222 },
      rf: { liters: 333, amount: 444 },
      doha: { liters: 555, amount: 666 },
      e1card: { liters: 777, amount: 888 },
    },
    fuelLitersTotal: 1776,
    fuelAmountTotal: 2220,
    countryTotals: { kz: 53_000, ru: 73_000, uz: 250_000 },
    currencyBalances: { usd: 880, rub: 1600, kzt: 5000, uzs: 2_750_000 },
  },
};

function countryTable(name: string): HTMLElement {
  const heading = screen.getByRole('columnheader', { name });
  return heading.closest('table') as HTMLElement;
}

/** Body rows of the fuel table, as arrays of cell text. */
function fuelBodyRows(): string[][] {
  const table = screen.getByText('Fuel table').closest('section')!.querySelector('table')!;
  return Array.from(table.querySelectorAll('tbody tr')).map((tr) =>
    Array.from(tr.querySelectorAll('td')).map((td) => td.textContent ?? ''),
  );
}

describe('fuel table', () => {
  it('places every litre and amount in its own column', () => {
    renderWithProviders(<TripExpenseReportTables report={report} />);

    // row no, then (litres, amount) for KZ, RF, DOHA, E1CARD in that order.
    expect(fuelBodyRows()[0]).toEqual([
      '1', '111', '222', '333', '444', '555', '666', '777', '888',
    ]);
  });

  it('totals each fuel column under that column', () => {
    renderWithProviders(<TripExpenseReportTables report={report} />);

    const rows = fuelBodyRows();
    expect(rows[rows.length - 1]).toEqual([
      'Total', '111', '222', '333', '444', '555', '666', '777', '888',
    ]);
  });
});

describe('per-country expenses', () => {
  it('puts each country’s subtotal in that country’s own table', () => {
    renderWithProviders(<TripExpenseReportTables report={report} />);

    const kz = within(countryTable('Kazakhstan'));
    const ru = within(countryTable('Russia'));
    const uz = within(countryTable('Uzbekistan'));

    expect(kz.getByText('Subtotal').closest('tr')).toHaveTextContent(n(53_000));
    expect(ru.getByText('Subtotal').closest('tr')).toHaveTextContent(n(73_000));
    expect(uz.getByText('Subtotal').closest('tr')).toHaveTextContent(n(250_000));
  });

  it('files a line item under the country it was spent in', () => {
    renderWithProviders(<TripExpenseReportTables report={report} />);

    // "Platon" exists in both the KZ and RU tables with different amounts —
    // the case where a lookup ignoring `country` silently shows one twice.
    const kzPlaton = within(countryTable('Kazakhstan')).getByText('Platon').closest('tr');
    const ruPlaton = within(countryTable('Russia')).getByText('Platon').closest('tr');

    expect(kzPlaton).toHaveTextContent(n(41_000));
    expect(ruPlaton).toHaveTextContent(n(73_000));
  });

  it('shows a dash for a category with no spend, never a zero', () => {
    renderWithProviders(<TripExpenseReportTables report={report} />);

    // Nothing was spent on Adblue in Kazakhstan. Rendering "0" would read as
    // "the driver reported zero", not "the driver reported nothing".
    const adblue = within(countryTable('Kazakhstan')).getByText('Adblue').closest('tr');
    expect(adblue).toHaveTextContent('—');
    expect(adblue).not.toHaveTextContent('0');
  });
});

describe('currency balances', () => {
  it('renders the balance the server computed for each currency', () => {
    renderWithProviders(<TripExpenseReportTables report={report} />);

    const balances = screen.getByText('Currency balances').closest('section') as HTMLElement;

    expect(balances).toHaveTextContent(n(880));
    expect(balances).toHaveTextContent(n(1600));
    expect(balances).toHaveTextContent(n(5000));
    expect(balances).toHaveTextContent(n(2_750_000));
  });
});
