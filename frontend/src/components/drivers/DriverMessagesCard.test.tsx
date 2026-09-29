/**
 * The dispatcher's "message the driver" card. Two things matter: a template
 * fills the box rather than sending blind, and the history says honestly
 * whether the phone got it — "delivered" when no device took the push would
 * have the dispatcher waiting for a driver who was never told.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import type { DriverMessage } from '@/lib/driverMessages';

vi.mock('@/lib/driverMessages', () => ({
  driverMessagesApi: { list: vi.fn(), send: vi.fn() },
}));

const { driverMessagesApi } = await import('@/lib/driverMessages');
const { DriverMessagesCard } = await import('./DriverMessagesCard');

const message = (over: Partial<DriverMessage> = {}): DriverMessage => ({
  id: 'm-1',
  driver_id: 'd-1',
  truck_id: null,
  kind: 'dispatcher',
  title: 'Сообщение от диспетчера',
  body: 'Позвоните в офис',
  devices_delivered: 1,
  created_at: new Date().toISOString(),
  read_at: null,
  ...over,
});

describe('DriverMessagesCard', () => {
  it('fills the box from a template and sends the trimmed text', async () => {
    vi.mocked(driverMessagesApi.list).mockResolvedValue([]);
    vi.mocked(driverMessagesApi.send).mockResolvedValue(message());
    renderWithProviders(<DriverMessagesCard driverId="d-1" />);

    const send = await screen.findByRole('button', { name: /send|yuborish|отправить/i });
    expect(send).toBeDisabled();

    const templates = screen.getAllByRole('button').filter((b) => b !== send);
    fireEvent.click(templates[0]);
    const box = screen.getByRole('textbox') as HTMLTextAreaElement;
    expect(box.value.length).toBeGreaterThan(0);

    fireEvent.change(box, { target: { value: '  Позвоните  ' } });
    fireEvent.click(send);
    await waitFor(() =>
      expect(driverMessagesApi.send).toHaveBeenCalledWith('d-1', { body: 'Позвоните' }),
    );
  });

  it('marks a message no phone took as inbox-only, not delivered', async () => {
    vi.mocked(driverMessagesApi.list).mockResolvedValue([
      message({ id: 'a', devices_delivered: 0 }),
      message({ id: 'b', read_at: new Date().toISOString(), kind: 'gps_silent' }),
    ]);
    renderWithProviders(<DriverMessagesCard driverId="d-1" />);

    await screen.findAllByText('Позвоните в офис');
    expect(screen.getByText(/in app only|faqat ilovada|только в приложении/i)).toBeInTheDocument();
    expect(screen.getByText(/^(read|o[‘']qildi|прочитано)$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^(delivered|yetkazildi|доставлено)$/i)).not.toBeInTheDocument();
  });
});
