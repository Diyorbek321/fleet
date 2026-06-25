import { NEXT_STATUS, type TripStatus } from '../trips';

describe('NEXT_STATUS trip flow', () => {
  it('advances a linear trip from draft to delivered without skipping a step', () => {
    const visited: TripStatus[] = ['draft'];
    let current: TripStatus | null = 'draft';
    while ((current = NEXT_STATUS[current]) !== null) {
      visited.push(current);
    }
    expect(visited).toEqual([
      'draft',
      'planned',
      'loading',
      'en_route',
      'at_border',
      'delivered',
    ]);
  });

  it('treats delivered and cancelled as terminal states', () => {
    expect(NEXT_STATUS.delivered).toBeNull();
    expect(NEXT_STATUS.cancelled).toBeNull();
  });

  it('defines a transition entry for every status', () => {
    const statuses: TripStatus[] = [
      'draft',
      'planned',
      'loading',
      'en_route',
      'at_border',
      'delivered',
      'cancelled',
    ];
    for (const status of statuses) {
      expect(NEXT_STATUS).toHaveProperty(status);
    }
  });
});
