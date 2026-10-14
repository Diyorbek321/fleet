import { documentsLocked } from '../tripDocuments';

describe('when a driver may still change a document photo', () => {
  it('lets them while the trip is running', () => {
    for (const status of ['draft', 'planned', 'loading', 'en_route', 'at_border']) {
      expect(documentsLocked(status)).toBe(false);
    }
  });

  it('locks them once the trip is delivered or cancelled', () => {
    // The server refuses with 409 then; the app should not offer what it refuses.
    expect(documentsLocked('delivered')).toBe(true);
    expect(documentsLocked('cancelled')).toBe(true);
  });
});
