/**
 * The map is only as current as its live connection. When that drops the
 * markers freeze where they were — and frozen looks exactly like parked, so
 * the map says so.
 */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';

import { renderWithProviders } from '@/test/render';
import { MapLegend } from './MapLegend';

describe('MapLegend connection state', () => {
  it('says the map is live', () => {
    renderWithProviders(<MapLegend live />);
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('says when the live connection dropped', () => {
    renderWithProviders(<MapLegend live={false} />);
    expect(screen.getByText(/Connection lost/)).toBeInTheDocument();
  });
});
