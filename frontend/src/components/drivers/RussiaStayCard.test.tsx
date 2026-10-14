/**
 * The desk's view of one driver's days in Russia. What matters: the deadline
 * is the one the server worked out (not entry + 90), an overstay reads as
 * one, and a stay the app missed can be typed in from the migration card.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import type { DriverStays } from '@/lib/russiaStays';

vi.mock('@/lib/russiaStays', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/russiaStays')>()),
  russiaStaysApi: { forDriver: vi.fn(), add: vi.fn(), update: vi.fn(), remove: vi.fn(), fleet: vi.fn() },
}));

const { russiaStaysApi } = await import('@/lib/russiaStays');
const { RussiaStayCard } = await import('./RussiaStayCard');

const inside: DriverStays = {
  summary: {
    in_russia: true,
    entered_on: '2026-08-29',
    day_of_stay: 47,
    days_used: 47,
    days_available: 43,
    must_leave_by: '2026-11-26',
    days_to_leave: 43,
    overstay_days: 0,
  },
  stays: [
    { id: 's1', entered_on: '2026-08-29', left_on: null, source: 'auto', trip_id: 't1', note: null },
  ],
};

describe('RussiaStayCard', () => {
  beforeEach(() => vi.mocked(russiaStaysApi.forDriver).mockReset());

  it('shows the day of the stay and the server’s deadline', async () => {
    vi.mocked(russiaStaysApi.forDriver).mockResolvedValue(inside);
    renderWithProviders(<RussiaStayCard driverId="d-1" />);

    expect(await screen.findByText('26.11.2026')).toBeInTheDocument();
    expect(screen.getByText('day 47')).toBeInTheDocument();
    expect(screen.getByText('43 days left')).toBeInTheDocument();
  });

  it('calls an overstay an overstay', async () => {
    vi.mocked(russiaStaysApi.forDriver).mockResolvedValue({
      ...inside,
      summary: { ...inside.summary, day_of_stay: 96, days_used: 96, days_to_leave: -6, overstay_days: 6 },
    });
    renderWithProviders(<RussiaStayCard driverId="d-1" />);

    expect(await screen.findByText(/Overstay/i)).toBeInTheDocument();
  });

  it('records a stay typed in from the migration card', async () => {
    vi.mocked(russiaStaysApi.forDriver).mockResolvedValue({
      summary: { ...inside.summary, in_russia: false, day_of_stay: null, must_leave_by: null, days_to_leave: null, days_used: 0, days_available: 90 },
      stays: [],
    });
    vi.mocked(russiaStaysApi.add).mockResolvedValue(inside.stays[0]);
    renderWithProviders(<RussiaStayCard driverId="d-1" />);

    fireEvent.click(await screen.findByRole('button', { name: /Add entry/i }));
    fireEvent.change(screen.getByLabelText(/Entered/i), { target: { value: '2026-10-01' } });
    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    await waitFor(() =>
      expect(russiaStaysApi.add).toHaveBeenCalledWith('d-1', { entered_on: '2026-10-01', left_on: null, note: null }),
    );
  });
});
