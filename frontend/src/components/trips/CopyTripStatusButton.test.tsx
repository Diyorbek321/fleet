/**
 * The copy button hands the dispatcher the server's card, verbatim. What can
 * go wrong here is the clipboard: it refuses on an insecure origin or after
 * the click's gesture has lapsed, and a button that silently does nothing is
 * worse than one that shows the text to copy by hand.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import { tripsApi } from '@/lib/trips';

import { CopyTripStatusButton } from './CopyTripStatusButton';

const CARD = 'Angren TEK\n\nРейс: TR-1\nСтатус: На границе УЗБ–КЗ';

function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
}

afterEach(() => vi.restoreAllMocks());

describe('CopyTripStatusButton', () => {
  it('puts the trip card on the clipboard', async () => {
    vi.spyOn(tripsApi, 'card').mockResolvedValue(CARD);
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);

    renderWithProviders(<CopyTripStatusButton tripId="t-1" />);
    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(CARD));
    expect(tripsApi.card).toHaveBeenCalledWith('t-1');
  });

  it('shows the text for a manual copy when the clipboard refuses', async () => {
    vi.spyOn(tripsApi, 'card').mockResolvedValue(CARD);
    stubClipboard(() => Promise.reject(new Error('denied')));
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue(null);

    renderWithProviders(<CopyTripStatusButton tripId="t-1" />);
    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => expect(prompt).toHaveBeenCalledWith(expect.any(String), CARD));
  });
});
