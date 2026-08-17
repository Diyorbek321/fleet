/**
 * The leakage page is the product's actual pitch: "your fleet lost this much
 * money, here is where". Every number on it is an accusation against a driver,
 * so it is exactly the screen where a presentation slip — right figure, wrong
 * unit or wrong row — does real damage. Commit f846cea shipped one of these
 * (fuel reported in dollars and MPG instead of so'm and L/100km) and nothing
 * caught it; these tests cover that class.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import type { FuelAnomalyRow, LeakageSummary, UnauthorizedStop } from '@/lib/analytics';

const summary: LeakageSummary = {
  windowDays: 30,
  estimatedFuelWasteCost: 12_450_000,
  flaggedTrucks: 2,
  fuelBaselineLPer100km: 34.5,
  unauthorizedStopCount: 3,
  totalIdleHours: 41.5,
  activeTrips: 7,
  deliveredTrips: 12,
};

const flaggedTruck: FuelAnomalyRow = {
  truckId: 'truck-1',
  truckName: 'Volvo FH',
  plateNumber: '01A123BC',
  distanceKm: 2400,
  liters: 1180,
  lPer100km: 49.2,
  baselineLPer100km: 34.5,
  flagged: true,
  estimatedWasteCost: 8_200_000,
};

const cleanTruck: FuelAnomalyRow = {
  truckId: 'truck-2',
  truckName: 'MAN TGX',
  plateNumber: '01B456CD',
  distanceKm: 1900,
  liters: 640,
  lPer100km: 33.7,
  baselineLPer100km: 34.5,
  flagged: false,
  estimatedWasteCost: 0,
};

const stop: UnauthorizedStop = {
  truckId: 'truck-1',
  truckName: 'Volvo FH',
  plateNumber: '01A123BC',
  latitude: 41.311081,
  longitude: 69.240562,
  startedAt: '2026-08-10T09:00:00Z',
  endedAt: '2026-08-10T11:30:00Z',
  durationMinutes: 150.4,
};

vi.mock('@/lib/analytics', () => ({
  analyticsApi: {
    leakageSummary: vi.fn(),
    fuelAnomalies: vi.fn(),
    unauthorizedStops: vi.fn(),
  },
}));

const { analyticsApi } = await import('@/lib/analytics');
const LeakagePage = (await import('./LeakagePage')).default;

function mockData(options: {
  summary?: LeakageSummary | null;
  fuel?: FuelAnomalyRow[];
  stops?: UnauthorizedStop[];
} = {}) {
  vi.mocked(analyticsApi.leakageSummary).mockResolvedValue(options.summary ?? summary);
  vi.mocked(analyticsApi.fuelAnomalies).mockResolvedValue(options.fuel ?? []);
  vi.mocked(analyticsApi.unauthorizedStops).mockResolvedValue(options.stops ?? []);
}

describe('LeakagePage summary cards', () => {
  it('reports fuel waste in so’m, not dollars', async () => {
    mockData();
    renderWithProviders(<LeakagePage />);

    // Grouped thousands + an explicit UZS suffix. A "$" or a bare number here
    // is the f846cea regression.
    expect(await screen.findByText('12,450,000 UZS')).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });

  it('reports the fuel baseline in L/100km, not MPG', async () => {
    mockData();
    renderWithProviders(<LeakagePage />);

    expect(await screen.findByText('34.5 L/100km')).toBeInTheDocument();
    expect(screen.queryByText(/MPG/i)).not.toBeInTheDocument();
  });

  it('puts each figure under its own label', async () => {
    mockData();
    renderWithProviders(<LeakagePage />);

    // Idle hours and stop count are single small numbers and are trivially
    // swappable; assert each sits in the card that names it. Anchoring on the
    // *value* (not the label) also waits for the query — labels render first,
    // against a placeholder zero.
    const idleCard = (await screen.findByText('41.5 h')).closest('div[class*="rounded"]');
    expect(idleCard).toHaveTextContent('Idle hours');

    const stopsCard = (await screen.findByText('3')).closest('div[class*="rounded"]');
    expect(stopsCard).toHaveTextContent('Unauthorized stops');
  });

  it('renders zeroes rather than blanks while the summary is still loading', async () => {
    mockData({ summary: null as unknown as LeakageSummary });
    renderWithProviders(<LeakagePage />);

    expect(await screen.findByText('0 UZS')).toBeInTheDocument();
  });
});

describe('LeakagePage fuel table', () => {
  it('flags only the truck the backend flagged', async () => {
    mockData({ fuel: [flaggedTruck, cleanTruck] });
    renderWithProviders(<LeakagePage />);

    const flaggedRow = (await screen.findByText('01A123BC')).closest('tr') as HTMLElement;
    const cleanRow = screen.getByText('01B456CD').closest('tr') as HTMLElement;

    expect(within(flaggedRow).getByText('Flagged')).toBeInTheDocument();
    expect(within(cleanRow).queryByText('Flagged')).not.toBeInTheDocument();
  });

  it('shows the truck’s own burn rate against the fleet baseline', async () => {
    mockData({ fuel: [flaggedTruck] });
    renderWithProviders(<LeakagePage />);

    const row = (await screen.findByText('01A123BC')).closest('tr') as HTMLElement;
    expect(within(row).getByText('2400 km')).toBeInTheDocument();
    expect(within(row).getByText('1180 L')).toBeInTheDocument();
    expect(within(row).getByText('49.2')).toBeInTheDocument();
    expect(within(row).getByText('/ 34.5')).toBeInTheDocument();
    expect(within(row).getByText('8,200,000 UZS')).toBeInTheDocument();
  });

  it('shows a dash, not "0 UZS", when a truck wasted nothing', async () => {
    mockData({ fuel: [cleanTruck] });
    renderWithProviders(<LeakagePage />);

    const row = (await screen.findByText('01B456CD')).closest('tr') as HTMLElement;
    expect(within(row).getByText('—')).toBeInTheDocument();
    expect(within(row).queryByText('0 UZS')).not.toBeInTheDocument();
  });

  it('says so when there is no fuel data instead of showing an empty table', async () => {
    mockData({ fuel: [] });
    renderWithProviders(<LeakagePage />);

    expect(await screen.findByText('No fuel data for this window')).toBeInTheDocument();
  });
});

describe('LeakagePage stops table', () => {
  it('links each stop to its coordinates on a map', async () => {
    mockData({ stops: [stop] });
    renderWithProviders(<LeakagePage />);

    const link = await screen.findByRole('link', { name: '41.3111, 69.2406' });
    expect(link).toHaveAttribute('href', 'https://maps.google.com/?q=41.311081,69.240562');
  });

  it('rounds the stop duration to whole minutes', async () => {
    mockData({ stops: [stop] });
    renderWithProviders(<LeakagePage />);

    expect(await screen.findByText('150 min')).toBeInTheDocument();
  });

  it('says so when no unauthorized stop was detected', async () => {
    mockData({ stops: [] });
    renderWithProviders(<LeakagePage />);

    expect(await screen.findByText('No unauthorized stops detected')).toBeInTheDocument();
  });
});

describe('LeakagePage window', () => {
  it('requests the 30-day window by default', async () => {
    mockData();
    renderWithProviders(<LeakagePage />);

    await waitFor(() => expect(analyticsApi.leakageSummary).toHaveBeenCalledWith(30));
    expect(analyticsApi.fuelAnomalies).toHaveBeenCalledWith(30);
    expect(analyticsApi.unauthorizedStops).toHaveBeenCalledWith(30);
  });
});
