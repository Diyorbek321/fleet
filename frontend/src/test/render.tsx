import type { ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, type RenderResult } from '@testing-library/react';
import { I18nextProvider } from 'react-i18next';

import i18n from '@/i18n';

/**
 * Render a component with the providers every page assumes exist.
 *
 * Retries are off and the cache is per-render so a failed query surfaces
 * immediately instead of being retried into a timeout, and no state leaks
 * between tests.
 *
 * The language is pinned to English: assertions match label text, and the
 * detector would otherwise pick whatever the environment reports.
 */
export function renderWithProviders(ui: ReactElement): RenderResult {
  void i18n.changeLanguage('en');
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </I18nextProvider>,
  );
}
