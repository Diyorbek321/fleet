/**
 * The card an owner uses to connect Telegram — and the one place where a
 * presentation bug costs the whole alerting feature.
 *
 * Three failures are worth a test each. A deep link the owner cannot get onto
 * their phone means the chat is never bound and nothing is ever delivered. A
 * mute toggle that sends the wrong list silences the alert the owner wanted
 * kept, and they only find out by not being told something. And a non-admin
 * who can reach the controls can quietly redirect or kill the director's
 * alerts, which is exactly what the token-only binding exists to prevent.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import type { AuthUser, UserRole } from '@/lib/api';
import type { TelegramAccount } from '@/lib/ownerAlerts';

vi.mock('@/lib/ownerAlerts', async () => {
  // The constants and formatters are real — the ordering of the toggles and
  // the hour labels are part of what these tests check.
  const actual = await vi.importActual<typeof import('@/lib/ownerAlerts')>('@/lib/ownerAlerts');
  return {
    ...actual,
    ownerAlertsApi: {
      list: vi.fn(),
      link: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
      test: vi.fn(),
    },
  };
});

vi.mock('@/contexts/AuthContext', () => ({ useAuth: vi.fn() }));

const { ownerAlertsApi } = await import('@/lib/ownerAlerts');
const { useAuth } = await import('@/contexts/AuthContext');
const { TelegramAlertsCard } = await import('./TelegramAlertsCard');

function signedInAs(role: UserRole): void {
  const user: AuthUser = {
    id: 'user-1',
    org_id: 'org-1',
    email: 'owner@example.com',
    role,
    must_change_password: false,
  };
  vi.mocked(useAuth).mockReturnValue({
    user,
    isAuthenticated: true,
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    changePassword: vi.fn(),
  });
}

const account = (over: Partial<TelegramAccount> = {}): TelegramAccount => ({
  id: 'acc-1',
  user_id: null,
  label: 'Direktor',
  activated: true,
  activated_at: '2026-09-01T08:00:00Z',
  is_active: true,
  muted_kinds: [],
  min_severity: 'warning',
  quiet_from_hour: 22,
  quiet_to_hour: 7,
  deep_link: null,
  created_at: '2026-09-01T07:00:00Z',
  ...over,
});

const pending = account({
  activated: false,
  activated_at: null,
  deep_link: 'https://t.me/fleetbot?start=owner_abc123',
});

function listReturns(accounts: TelegramAccount[]): void {
  vi.mocked(ownerAlertsApi.list).mockResolvedValue(accounts);
}

describe('TelegramAlertsCard with nothing linked', () => {
  it('tells the admin how to start instead of showing an empty list', async () => {
    signedInAs('admin');
    listReturns([]);
    renderWithProviders(<TelegramAlertsCard />);

    expect(await screen.findByText(/No chat connected yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect Telegram' })).toBeInTheDocument();
  });

  it('mints a link with the label the admin typed', async () => {
    signedInAs('admin');
    listReturns([]);
    vi.mocked(ownerAlertsApi.link).mockResolvedValue({
      id: 'acc-1',
      token: 'abc123',
      deep_link: pending.deep_link as string,
      label: 'Buxgalter',
    });
    renderWithProviders(<TelegramAlertsCard />);

    fireEvent.change(await screen.findByLabelText("Who it's for (optional)"), {
      target: { value: 'Buxgalter' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Connect Telegram' }));

    await waitFor(() =>
      expect(ownerAlertsApi.link).toHaveBeenCalledWith({ label: 'Buxgalter' }),
    );
  });

  it('sends no label rather than an empty one when the field is left blank', async () => {
    signedInAs('admin');
    listReturns([]);
    vi.mocked(ownerAlertsApi.link).mockResolvedValue({
      id: 'acc-1',
      token: 'abc123',
      deep_link: pending.deep_link as string,
      label: null,
    });
    renderWithProviders(<TelegramAlertsCard />);

    fireEvent.click(await screen.findByRole('button', { name: 'Connect Telegram' }));

    // `''` would be stored and then shown as this chat's name, which reads as
    // a chat with a blank label rather than one that was never named.
    await waitFor(() => expect(ownerAlertsApi.link).toHaveBeenCalledWith({ label: null }));
  });
});

describe('TelegramAlertsCard awaiting activation', () => {
  it('offers the deep link both as a link and as text that can be copied', async () => {
    signedInAs('admin');
    listReturns([pending]);
    renderWithProviders(<TelegramAlertsCard />);

    // The owner may be on a desktop with Telegram on their phone: an anchor
    // alone strands them, and the raw string alone costs them a tap.
    const link = await screen.findByRole('link', { name: /Open in Telegram/ });
    expect(link).toHaveAttribute('href', pending.deep_link);
    expect(screen.getByText(pending.deep_link as string)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument();
  });

  it('shows the chat as waiting and offers no test message yet', async () => {
    signedInAs('admin');
    listReturns([pending]);
    renderWithProviders(<TelegramAlertsCard />);

    expect(await screen.findByText('Waiting to be opened')).toBeInTheDocument();
    // The backend rejects a test on an unbound chat with a 400; a button that
    // can only fail is worse than no button.
    expect(screen.queryByRole('button', { name: 'Test message' })).not.toBeInTheDocument();
    // Preferences belong to a chat that exists. There is nothing to tune yet.
    expect(screen.queryByRole('switch', { name: 'Fuel waste' })).not.toBeInTheDocument();
  });
});

describe('TelegramAlertsCard once active', () => {
  it('names each alert kind instead of showing the backend enum', async () => {
    signedInAs('admin');
    listReturns([account()]);
    renderWithProviders(<TelegramAlertsCard />);

    expect(await screen.findByRole('switch', { name: "Cash doesn't reconcile" })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Overdue service' })).toBeInTheDocument();
    expect(screen.queryByText(/cash_mismatch|maintenance_overdue/)).not.toBeInTheDocument();
  });

  it('shows a muted kind as off and everything else as on', async () => {
    signedInAs('admin');
    listReturns([account({ muted_kinds: ['trip_status'] })]);
    renderWithProviders(<TelegramAlertsCard />);

    // The switch reads positively ("send me this"), so a muted kind must be
    // unchecked. Inverting this is the bug that silences an owner who thought
    // they were turning something on.
    expect(await screen.findByRole('switch', { name: 'Trip status change' })).not.toBeChecked();
    expect(screen.getByRole('switch', { name: 'Fuel waste' })).toBeChecked();
  });

  it('adds only the switched-off kind to the mute list', async () => {
    signedInAs('admin');
    listReturns([account({ muted_kinds: ['briefing'] })]);
    vi.mocked(ownerAlertsApi.update).mockResolvedValue(
      account({ muted_kinds: ['briefing', 'trip_status'] }),
    );
    renderWithProviders(<TelegramAlertsCard />);

    fireEvent.click(await screen.findByRole('switch', { name: 'Trip status change' }));

    // Already-muted kinds must survive: a patch that sends only the kind just
    // clicked un-mutes everything else in one click.
    await waitFor(() =>
      expect(ownerAlertsApi.update).toHaveBeenCalledWith('acc-1', {
        muted_kinds: ['briefing', 'trip_status'],
      }),
    );
  });

  it('un-mutes a kind by removing it from the list', async () => {
    signedInAs('admin');
    listReturns([account({ muted_kinds: ['briefing', 'leakage'] })]);
    vi.mocked(ownerAlertsApi.update).mockResolvedValue(account({ muted_kinds: ['briefing'] }));
    renderWithProviders(<TelegramAlertsCard />);

    fireEvent.click(await screen.findByRole('switch', { name: 'Fuel waste' }));

    await waitFor(() =>
      expect(ownerAlertsApi.update).toHaveBeenCalledWith('acc-1', { muted_kinds: ['briefing'] }),
    );
  });

  it('describes the minimum severity in words, not as a level name', async () => {
    signedInAs('admin');
    listReturns([account({ min_severity: 'critical' })]);
    renderWithProviders(<TelegramAlertsCard />);

    expect(await screen.findByText('Critical only')).toBeInTheDocument();
    expect(screen.queryByText('critical')).not.toBeInTheDocument();
  });

  it('shows the quiet window as whole hours', async () => {
    signedInAs('admin');
    listReturns([account({ quiet_from_hour: 22, quiet_to_hour: 7 })]);
    renderWithProviders(<TelegramAlertsCard />);

    expect(await screen.findByText('22:00')).toBeInTheDocument();
    expect(screen.getByText('07:00')).toBeInTheDocument();
  });

  it('clears both ends of the window when quiet hours are switched off', async () => {
    signedInAs('admin');
    listReturns([account()]);
    vi.mocked(ownerAlertsApi.update).mockResolvedValue(
      account({ quiet_from_hour: null, quiet_to_hour: null }),
    );
    renderWithProviders(<TelegramAlertsCard />);

    fireEvent.click(await screen.findByRole('switch', { name: 'Quiet hours' }));

    // A half-cleared window (one hour null) is a state the backend has no
    // reading for.
    await waitFor(() =>
      expect(ownerAlertsApi.update).toHaveBeenCalledWith('acc-1', {
        quiet_from_hour: null,
        quiet_to_hour: null,
      }),
    );
  });

  it('hides the hour pickers while there is no quiet window', async () => {
    signedInAs('admin');
    listReturns([account({ quiet_from_hour: null, quiet_to_hour: null })]);
    renderWithProviders(<TelegramAlertsCard />);

    expect(await screen.findByRole('switch', { name: 'Quiet hours' })).not.toBeChecked();
    expect(screen.queryByLabelText('From')).not.toBeInTheDocument();
  });

  it('sends a test message on demand', async () => {
    signedInAs('admin');
    listReturns([account()]);
    vi.mocked(ownerAlertsApi.test).mockResolvedValue({ sent: true });
    renderWithProviders(<TelegramAlertsCard />);

    fireEvent.click(await screen.findByRole('button', { name: 'Test message' }));

    await waitFor(() => expect(ownerAlertsApi.test).toHaveBeenCalledWith('acc-1'));
  });

  it('asks before unlinking, and unlinks nothing until confirmed', async () => {
    signedInAs('admin');
    listReturns([account()]);
    vi.mocked(ownerAlertsApi.remove).mockResolvedValue(undefined);
    renderWithProviders(<TelegramAlertsCard />);

    fireEvent.click(await screen.findByRole('button', { name: 'Unlink' }));

    const dialog = await screen.findByRole('alertdialog');
    expect(ownerAlertsApi.remove).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Unlink' }));
    await waitFor(() => expect(ownerAlertsApi.remove).toHaveBeenCalledWith('acc-1'));
  });

  it('marks a silenced chat as paused rather than active', async () => {
    signedInAs('admin');
    listReturns([account({ is_active: false })]);
    renderWithProviders(<TelegramAlertsCard />);

    // The owner's own /stop lands here. Showing it as active would leave an
    // admin wondering why nothing arrives.
    expect(await screen.findByText('Paused')).toBeInTheDocument();
    expect(screen.queryByText('Active')).not.toBeInTheDocument();
  });
});

describe('TelegramAlertsCard for a non-admin', () => {
  it('shows the state without any way to change it', async () => {
    signedInAs('manager');
    listReturns([account()]);
    renderWithProviders(<TelegramAlertsCard />);

    // A manager may look — knowing where alerts go is part of the job — but
    // linking, unlinking and muting are the admin's alone, and the backend
    // refuses them regardless. Leaving the controls live would only produce
    // 403s the manager cannot act on.
    expect(await screen.findByText('Direktor')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Fuel waste' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Connect Telegram' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Test message' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Unlink' })).not.toBeInTheDocument();
    expect(screen.getByText('Only an admin can change these.')).toBeInTheDocument();
  });
});
