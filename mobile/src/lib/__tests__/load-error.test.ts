import { ApiError } from '../api';
import { loadErrorMessage } from '../load-error';

const t = (key: string) => `t:${key}`;

describe('loadErrorMessage', () => {
  it('turns a request that never reached the server into the offline text', () => {
    expect(loadErrorMessage(new ApiError(0, 'Network request failed'), t)).toBe(
      't:common.networkError',
    );
  });

  it('keeps the server-side reason for an HTTP failure', () => {
    expect(loadErrorMessage(new ApiError(500, 'Internal Server Error'), t)).toBe(
      'Internal Server Error',
    );
  });

  it('keeps the message of any other Error', () => {
    expect(loadErrorMessage(new Error('boom'), t)).toBe('boom');
  });

  it('falls back to the generic text when there is nothing to show', () => {
    expect(loadErrorMessage(new Error(''), t)).toBe('t:common.error');
    expect(loadErrorMessage('weird', t)).toBe('t:common.error');
  });
});
