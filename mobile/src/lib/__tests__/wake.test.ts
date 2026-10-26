/**
 * The server wakes a quiet phone with a data-only push. Android hands the
 * fields over either as they are or as a JSON string, depending on how the
 * app was started; both must read as a wake-up, and nothing else must.
 */
import { isWake } from '../wake';

describe('isWake', () => {
  it('reads the fields as sent', () => {
    expect(isWake({ notification: null, data: { kind: 'wake' } })).toBe(true);
  });

  it('reads them from the JSON string', () => {
    expect(isWake({ notification: null, data: { dataString: '{"kind":"wake"}' } })).toBe(true);
  });

  it('ignores an ordinary message push and junk', () => {
    expect(isWake({ notification: {}, data: { kind: 'message' } })).toBe(false);
    expect(isWake({ notification: null, data: { dataString: 'not json' } })).toBe(false);
    expect(isWake(undefined)).toBe(false);
  });
});
