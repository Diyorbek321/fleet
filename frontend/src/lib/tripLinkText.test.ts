import { describe, it, expect } from 'vitest';
import { buildTripLinkText } from './tripLinkText';

const t = (key: string) => key.split('.').pop() ?? key;

describe('buildTripLinkText', () => {
  it('prints the route, the unloading date and both links', () => {
    const text = buildTripLinkText(
      {
        reference: 'Silk-0012',
        originName: 'Елабуга',
        destinationName: 'Ташкент',
        scheduledEnd: '2026-10-12T12:00:00Z',
      },
      { deepLink: 'https://t.me/bot?start=x', trackUrl: 'https://fleet.example/track/abc' },
      t,
    );
    expect(text).toBe(
      [
        'trip: Silk-0012',
        'from: Елабуга',
        'to: Ташкент',
        'unloading: 12.10.2026',
        '',
        'map: https://fleet.example/track/abc',
        'telegram: https://t.me/bot?start=x',
      ].join('\n'),
    );
  });

  it('leaves out what the trip does not know', () => {
    const text = buildTripLinkText(
      { reference: 'R-1', originName: null, destinationName: '  ', scheduledEnd: null },
      { deepLink: 'https://t.me/bot?start=y', trackUrl: null },
      t,
    );
    expect(text).toBe(['trip: R-1', '', 'telegram: https://t.me/bot?start=y'].join('\n'));
  });
});
