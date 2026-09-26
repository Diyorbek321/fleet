/**
 * The switch a dispatcher flips, and the switch a tracker flips, are not the
 * same switch.
 *
 * Taking a truck off the board used to write `status: 'offline'` — a lie about
 * GPS that the next real ping quietly overwrote, putting the truck back in
 * service on its own. These tests pin the two apart.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import { TruckProvider, useTrucks } from '@/contexts/TruckContext';
import type { Truck } from '@/types';

vi.mock('@/hooks/useLiveLocations', () => ({
  useLiveLocations: () => ({ locations: {}, isConnected: false }),
}));

const listMock = vi.fn();
const updateMock = vi.fn();

vi.mock('@/lib/trucks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/trucks')>();
  return {
    ...actual,
    trucksApi: {
      list: () => listMock(),
      update: (id: string, patch: unknown) => updateMock(id, patch),
      create: vi.fn(),
      remove: vi.fn(),
      get: vi.fn(),
      getDetails: vi.fn(),
    },
  };
});

vi.mock('@/lib/locations', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/locations')>();
  return { ...actual, fetchTruckLocationLabels: vi.fn(async () => ({})) };
});

function truck(overrides: Partial<Truck> = {}): Truck {
  return {
    id: 't-1',
    plateNumber: '01A123BC',
    name: 'Alpha',
    status: 'offline',
    speed: 0,
    latitude: 0,
    longitude: 0,
    address: null,
    lastUpdate: new Date('2026-09-01T00:00:00Z'),
    isEnabled: true,
    ...overrides,
  };
}

function Consumer() {
  const { trucks, toggleTruckEnabled } = useTrucks();
  return (
    <div>
      <button onClick={() => void toggleTruckEnabled('t-1')}>toggle</button>
      {trucks.map((t) => (
        <span key={t.id} data-testid="row">
          {t.plateNumber}:{t.isEnabled ? 'in-service' : 'off-board'}
        </span>
      ))}
    </div>
  );
}

async function renderWith(initial: Truck) {
  listMock.mockResolvedValue([initial]);
  renderWithProviders(
    <TruckProvider>
      <Consumer />
    </TruckProvider>,
  );
  await screen.findByTestId('row');
}

describe('toggleTruckEnabled', () => {
  beforeEach(() => {
    listMock.mockReset();
    updateMock.mockReset();
    updateMock.mockResolvedValue(truck({ isEnabled: false }));
  });

  it('flips the dispatcher flag and leaves the GPS status alone', async () => {
    await renderWith(truck({ isEnabled: true }));

    await act(async () => {
      fireEvent.click(screen.getByText('toggle'));
    });

    expect(updateMock).toHaveBeenCalledWith('t-1', { isEnabled: false });
    expect(updateMock.mock.calls[0][1]).not.toHaveProperty('status');
  });

  it('puts a truck back in service without pretending it has a fix', async () => {
    await renderWith(truck({ isEnabled: false }));

    await act(async () => {
      fireEvent.click(screen.getByText('toggle'));
    });

    expect(updateMock).toHaveBeenCalledWith('t-1', { isEnabled: true });
  });

  it('keeps a truck with no GPS fix in service', async () => {
    // The regression: `offline` is the state of every truck on the day it is
    // added, and it used to read as "switched off".
    await renderWith(truck({ status: 'offline', isEnabled: true }));

    expect(screen.getByTestId('row')).toHaveTextContent('01A123BC:in-service');
  });
});
