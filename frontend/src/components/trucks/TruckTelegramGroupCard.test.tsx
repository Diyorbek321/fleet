/**
 * The truck's group card. The dispatcher has to be able to tell, without
 * opening Telegram, whether orders are actually reaching a group — "lost"
 * (bot removed) must not look like "linked".
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import type { TruckGroup } from '@/lib/truckGroups';

vi.mock('@/lib/truckGroups', () => ({
  truckGroupsApi: { get: vi.fn(), link: vi.fn(), unlink: vi.fn() },
}));

const { truckGroupsApi } = await import('@/lib/truckGroups');
const { TruckTelegramGroupCard } = await import('./TruckTelegramGroupCard');

const group = (over: Partial<TruckGroup>): TruckGroup => ({
  status: 'none',
  chat_title: null,
  activated_at: null,
  deep_link: null,
  ...over,
});

describe('TruckTelegramGroupCard', () => {
  it('links a group by opening the startgroup link', async () => {
    const link = 'https://t.me/FleetBot?startgroup=truck_abc';
    vi.mocked(truckGroupsApi.get).mockResolvedValue(group({}));
    vi.mocked(truckGroupsApi.link).mockResolvedValue(group({ status: 'pending', deep_link: link }));
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    renderWithProviders(<TruckTelegramGroupCard truckId="t-1" />);

    fireEvent.click(await screen.findByRole('button', { name: /link group/i }));
    await waitFor(() => expect(open).toHaveBeenCalledWith(link, '_blank', 'noopener'));
    expect(await screen.findByText(link)).toBeInTheDocument();
  });

  it('shows which group is linked', async () => {
    vi.mocked(truckGroupsApi.get).mockResolvedValue(
      group({ status: 'linked', chat_title: '01A123BC Anvar', activated_at: new Date().toISOString() }),
    );
    renderWithProviders(<TruckTelegramGroupCard truckId="t-1" />);
    expect(await screen.findByText('01A123BC Anvar')).toBeInTheDocument();
    expect(screen.getByText(/^linked$/i)).toBeInTheDocument();
  });

  it('says so when the bot was removed from the group', async () => {
    vi.mocked(truckGroupsApi.get).mockResolvedValue(
      group({ status: 'lost', chat_title: '01A123BC Anvar', activated_at: new Date().toISOString() }),
    );
    renderWithProviders(<TruckTelegramGroupCard truckId="t-1" />);
    expect(await screen.findByText(/bot removed from group/i)).toBeInTheDocument();
    expect(screen.queryByText(/^linked$/i)).not.toBeInTheDocument();
  });
});
