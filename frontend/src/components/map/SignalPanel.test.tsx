/**
 * The map only draws trucks that have a position. This panel is how the
 * dispatcher learns about the rest — a truck that is simply absent from the
 * map reads as "the map is complete", which is the mistake it exists to stop.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import type { TruckSignal } from '@/lib/signal';

vi.mock('@/lib/signal', () => ({ fetchTruckSignal: vi.fn() }));

const { fetchTruckSignal } = await import('@/lib/signal');
const { SignalPanel } = await import('./SignalPanel');

function signal(overrides: Partial<TruckSignal>): TruckSignal {
  return {
    truckId: 't',
    plateNumber: '01A000AA',
    name: '01A000AA',
    state: 'ok',
    lastFixAt: new Date(),
    gpsDisabledAt: null,
    driverName: 'Anvar',
    driverPhone: '+998901234567',
    phoneBattery: null,
    phoneTracking: null,
    phoneAppVersion: null,
    ...overrides,
  };
}

describe('SignalPanel', () => {
  it('counts every truck that is not reporting, and none that is', async () => {
    vi.mocked(fetchTruckSignal).mockResolvedValue([
      signal({ truckId: 'a', plateNumber: '10 422 TCA', state: 'never', lastFixAt: null }),
      signal({ truckId: 'b', plateNumber: '10 433 TCA', state: 'no_driver', driverName: null }),
      signal({ truckId: 'c', plateNumber: '10 677 RCA', state: 'silent' }),
      signal({ truckId: 'd', plateNumber: 'LIVE', state: 'ok' }),
    ]);
    renderWithProviders(<SignalPanel onSelect={() => {}} />);

    expect(await screen.findByText('No signal: 3')).toBeInTheDocument();
    fireEvent.click(screen.getByText('No signal: 3'));
    expect(screen.getByText('10 422 TCA')).toBeInTheDocument();
    expect(screen.getByText('Never connected')).toBeInTheDocument();
    expect(screen.getByText('No driver assigned')).toBeInTheDocument();
    expect(screen.queryByText('LIVE')).not.toBeInTheDocument();
  });

  it('lets the dispatcher call the driver straight from the list', async () => {
    vi.mocked(fetchTruckSignal).mockResolvedValue([signal({ state: 'gps_off' })]);
    renderWithProviders(<SignalPanel onSelect={() => {}} />);

    fireEvent.click(await screen.findByText('No signal: 1'));
    expect(screen.getByText('GPS switched off')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /\+998901234567/ })).toHaveAttribute(
      'href',
      'tel:+998901234567',
    );
  });

  it('says so when the whole fleet is reporting', async () => {
    vi.mocked(fetchTruckSignal).mockResolvedValue([signal({ state: 'ok' })]);
    renderWithProviders(<SignalPanel onSelect={() => {}} />);

    expect(await screen.findByText('All trucks reporting')).toBeInTheDocument();
  });

  it('hands a truck with a last position to the map', async () => {
    const onSelect = vi.fn();
    vi.mocked(fetchTruckSignal).mockResolvedValue([
      signal({ truckId: 'x', plateNumber: 'OLD-1', state: 'silent' }),
    ]);
    renderWithProviders(<SignalPanel onSelect={onSelect} />);

    fireEvent.click(await screen.findByText('No signal: 1'));
    fireEvent.click(screen.getByText('OLD-1'));
    expect(onSelect).toHaveBeenCalledWith('x');
  });

  it('says what the phone last reported about itself', async () => {
    vi.mocked(fetchTruckSignal).mockResolvedValue([
      signal({ state: 'silent', phoneBattery: 0.04, phoneTracking: 'foreground', phoneAppVersion: '0.4.1' }),
    ]);
    renderWithProviders(<SignalPanel onSelect={() => {}} />);

    fireEvent.click(await screen.findByText('No signal: 1'));
    expect(screen.getByText(/4%/)).toBeInTheDocument();
    expect(screen.getByText(/only while open/i)).toBeInTheDocument();
    expect(screen.getByText(/v0\.4\.1/)).toBeInTheDocument();
  });
});
