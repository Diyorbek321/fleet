/**
 * The bell in the top bar. It must count what is new, clear the count when
 * opened, and keep the new entries highlighted while the menu is open —
 * clearing the highlight on open would hide the very thing the user clicked
 * the bell to find.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { renderWithProviders } from '@/test/render';
import type { NotificationFeed, PanelNotification } from '@/lib/notifications';

vi.mock('@/lib/notifications', async () => {
  const actual = await vi.importActual<typeof import('@/lib/notifications')>('@/lib/notifications');
  return { ...actual, notificationsApi: { feed: vi.fn(), markSeen: vi.fn() } };
});

const { notificationsApi } = await import('@/lib/notifications');
const { NotificationBell } = await import('./NotificationBell');

const seenAt = new Date(Date.now() - 60 * 60_000).toISOString();

const note = (over: Partial<PanelNotification> = {}): PanelNotification => ({
  id: 'n-1',
  kind: 'gps_signal',
  severity: 'warning',
  title: '01A123BC - Anvar - TR-1 — нет GPS 1 дн.',
  body: 'Последний сигнал: 28.09 09:00',
  path: '/trucks/t-1',
  created_at: new Date().toISOString(),
  ...over,
});

const feed = (over: Partial<NotificationFeed> = {}): NotificationFeed => ({
  items: [note()],
  unread_count: 1,
  seen_at: seenAt,
  ...over,
});

function openBell() {
  const trigger = screen.getByRole('button', { name: /notifications/i });
  // Radix opens on keyboard in jsdom; its pointer path needs PointerEvent.
  fireEvent.keyDown(trigger, { key: 'Enter' });
}

describe('NotificationBell', () => {
  it('shows the unread count, and opening it marks everything seen', async () => {
    vi.mocked(notificationsApi.feed).mockResolvedValue(feed());
    vi.mocked(notificationsApi.markSeen).mockResolvedValue(
      feed({ unread_count: 0, seen_at: new Date().toISOString() }),
    );
    renderWithProviders(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    );

    expect(await screen.findByText('1')).toBeInTheDocument();
    openBell();

    expect(await screen.findByText(/нет GPS 1 дн\./)).toBeInTheDocument();
    await waitFor(() => expect(notificationsApi.markSeen).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText('1')).not.toBeInTheDocument());
  });

  it('does not call the server when there is nothing new', async () => {
    vi.mocked(notificationsApi.feed).mockResolvedValue(feed({ items: [], unread_count: 0 }));
    vi.mocked(notificationsApi.markSeen).mockClear();
    renderWithProviders(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    );

    await waitFor(() => expect(notificationsApi.feed).toHaveBeenCalled());
    openBell();
    expect(await screen.findByText(/no notifications/i)).toBeInTheDocument();
    expect(notificationsApi.markSeen).not.toHaveBeenCalled();
  });
});
