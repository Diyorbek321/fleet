/**
 * The archive is where a delivered trip goes to be found again — for a
 * reconciliation, a dispute, a month-end count. Export and import are counted
 * apart, so each filter must ask the server for its own direction and never
 * show the other's trips.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { renderWithProviders } from '@/test/render';
import type { Trip, TripListFilter } from '@/lib/trips';

vi.mock('@/lib/trips', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/trips')>()),
  tripsApi: { list: vi.fn() },
}));

const { tripsApi } = await import('@/lib/trips');
const { TripsArchive } = await import('./TripsArchive');

function trip(overrides: Partial<Trip>): Trip {
  return {
    id: 'trip-x',
    reference: 'REF',
    status: 'delivered',
    direction: null,
    originName: 'Tashkent',
    destinationName: 'Moscow',
    truckId: 'truck-1',
    rate: 0,
    currency: 'USD',
    isLoaded: true,
    isReefer: false,
    deliveredAt: '2026-10-01T10:00:00Z',
    ...overrides,
  } as Trip;
}

const exportTrip = trip({ id: 'e1', reference: 'EXP-1', direction: 'uz_ru' });
const importTrip = trip({ id: 'i1', reference: 'IMP-1', direction: 'ru_uz', originName: 'Moscow', destinationName: 'Tashkent' });

function serveByDirection() {
  vi.mocked(tripsApi.list).mockImplementation(async (filter: TripListFilter = {}) => {
    if (filter.direction === 'uz_ru') return [exportTrip];
    if (filter.direction === 'ru_uz') return [importTrip];
    return [exportTrip, importTrip];
  });
}

function renderArchive() {
  return renderWithProviders(
    <MemoryRouter>
      <TripsArchive truckLabel={() => 'Volvo (01A123BC)'} />
    </MemoryRouter>,
  );
}

describe('TripsArchive', () => {
  beforeEach(() => vi.mocked(tripsApi.list).mockReset());

  it('asks the server for delivered trips only and lists them all by default', async () => {
    serveByDirection();
    renderArchive();

    expect(await screen.findByText('EXP-1')).toBeInTheDocument();
    expect(screen.getByText('IMP-1')).toBeInTheDocument();
    expect(vi.mocked(tripsApi.list).mock.calls[0][0]).toMatchObject({ archived: true, direction: undefined });
  });

  it('shows export trips alone under the export filter', async () => {
    serveByDirection();
    renderArchive();
    await screen.findByText('IMP-1');

    fireEvent.click(screen.getByRole('radio', { name: /Export/ }));

    await waitFor(() => expect(screen.queryByText('IMP-1')).not.toBeInTheDocument());
    expect(await screen.findByText('EXP-1')).toBeInTheDocument();
    expect(screen.queryByText('IMP-1')).not.toBeInTheDocument();
    expect(tripsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ archived: true, direction: 'uz_ru' }));
  });

  it('shows import trips alone under the import filter', async () => {
    serveByDirection();
    renderArchive();
    await screen.findByText('EXP-1');

    fireEvent.click(screen.getByRole('radio', { name: /Import/ }));

    await waitFor(() => expect(screen.queryByText('EXP-1')).not.toBeInTheDocument());
    expect(await screen.findByText('IMP-1')).toBeInTheDocument();
    expect(screen.queryByText('EXP-1')).not.toBeInTheDocument();
    expect(tripsApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ archived: true, direction: 'ru_uz' }));
  });

  it('names the empty filter rather than showing a bare table', async () => {
    vi.mocked(tripsApi.list).mockResolvedValue([]);
    renderArchive();

    expect(await screen.findByText('No trips in the archive yet')).toBeInTheDocument();
  });
});
