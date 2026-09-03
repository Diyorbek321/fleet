/**
 * The per-trip country breakdown.
 *
 * The arithmetic lives on the server (backend/tests/test_country_expenses.py).
 * What can go wrong *here* is meaning: three adjacent columns holding three
 * different currencies, where a mis-mapped country silently files roubles under
 * Kazakhstan and every cell still looks plausible — and a missing exchange rate,
 * which must read as "not converted" and never as "$0".
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { renderWithProviders } from '@/test/render';
import type { CountryBlock, CountryExpenseTrip } from '@/lib/countryExpenses';

import { CountryTripsTable } from './CountryTripsTable';
import { CountryTotalsCards } from './CountryTotalsCards';

const block = (over: Partial<CountryBlock> & Pick<CountryBlock, 'country' | 'currency'>): CountryBlock => ({
  lines: [],
  total: 0,
  total_usd: null,
  fuel_liters: 0,
  rate: null,
  rate_source: null,
  ...over,
});

// Distinct magnitudes per country so a column swapped with its neighbour
// cannot accidentally produce a matching number.
const uz = block({
  country: 'uz',
  currency: 'UZS',
  lines: [{ category: 'taxi', amount: 126_000, amount_usd: 10, liters: null }],
  total: 126_000,
  total_usd: 10,
  rate: 12_600,
  rate_source: 'org',
});

const kz = block({
  country: 'kz',
  currency: 'KZT',
  lines: [
    { category: 'fuel', amount: 104_000, amount_usd: 200, liters: 300 },
    { category: 'platon', amount: 26_000, amount_usd: 50, liters: null },
  ],
  total: 130_000,
  total_usd: 250,
  fuel_liters: 300,
  rate: 520,
  rate_source: 'trip',
});

const ru = block({
  country: 'ru',
  currency: 'RUB',
  lines: [{ category: 'platon', amount: 8_000, amount_usd: null, liters: null }],
  total: 8_000,
  total_usd: null,
});

const trip: CountryExpenseTrip = {
  trip_id: 't-1',
  reference: 'TR-2026-000042',
  truck_id: 'tr-1',
  truck_name: 'Volvo FH',
  plate_number: '01A123BC',
  driver_name: 'Anvar',
  trip_date: '2026-08-12',
  route: 'Tashkent → Moscow',
  distance_km: 6_400,
  report_status: 'submitted',
  countries: [uz, kz, ru],
  cards: [{ column: 'doha', liters: 150, amount: 180 }],
  total_usd: 260,
  usd_partial: true,
};

const renderTable = (trips: CountryExpenseTrip[]) =>
  renderWithProviders(
    <MemoryRouter>
      <CountryTripsTable trips={trips} />
    </MemoryRouter>,
  );

describe('CountryTripsTable', () => {
  it('shows each country in its own currency, in route order', () => {
    renderTable([trip]);
    const row = screen.getByText('TR-2026-000042').closest('tr')!;
    const cells = within(row).getAllByRole('cell').map((c) => c.textContent);

    // Chevron, trip, truck, date, km, then UZ / KZ / RU, then the USD total.
    expect(cells[5]).toContain('126,000 UZS');
    expect(cells[6]).toContain('130,000 KZT');
    expect(cells[7]).toContain('8,000 RUB');
  });

  it('marks a total built from only some of the countries', () => {
    renderTable([trip]);
    expect(screen.getByLabelText(/incomplete/i)).toBeInTheDocument();
  });

  it('itemises the trip only once it is opened', () => {
    renderTable([trip]);
    expect(screen.queryByText('Platon')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('TR-2026-000042').closest('tr')!);

    expect(screen.getAllByText('Platon').length).toBeGreaterThan(0);
    expect(screen.getByText('Fuel (GSM)')).toBeInTheDocument();
    // Card fuel is listed apart from the countries, with the reason said aloud.
    expect(screen.getByText(/settled centrally/i)).toBeInTheDocument();
  });

  it('says so when there are no trips rather than showing an empty grid', () => {
    renderTable([]);
    expect(screen.getByText(/No trips found/i)).toBeInTheDocument();
  });
});

describe('CountryTotalsCards', () => {
  it('leads with the native amount and keeps USD as the derived figure', () => {
    renderWithProviders(<CountryTotalsCards countries={[uz, kz, ru]} totalUsd={260} />);
    expect(screen.getByText('130,000 KZT')).toBeInTheDocument();
    expect(screen.getByText(/\$250\.00/)).toBeInTheDocument();
  });

  it('renders an unconverted country as a dash, never as zero', () => {
    renderWithProviders(<CountryTotalsCards countries={[ru]} totalUsd={null} />);
    expect(screen.getByText('8,000 RUB')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText(/\$0/)).not.toBeInTheDocument();
    expect(screen.getByText(/No rate set/i)).toBeInTheDocument();
  });

  it('names where a converted figure got its rate', () => {
    renderWithProviders(<CountryTotalsCards countries={[kz]} totalUsd={250} />);
    expect(screen.getByText(/1 USD = 520\.00 KZT \(trip's own rate\)/)).toBeInTheDocument();
  });

  it('drops countries with nothing spent instead of showing empty cards', () => {
    const untouched = block({ country: 'ru', currency: 'RUB' });
    renderWithProviders(<CountryTotalsCards countries={[kz, untouched]} totalUsd={250} />);
    expect(screen.queryByText('Russia')).not.toBeInTheDocument();
  });
});
