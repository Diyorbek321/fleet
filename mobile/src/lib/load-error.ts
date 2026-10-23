import { ApiError } from './api';

type LoadErrorKey = 'common.networkError' | 'common.error';
type Translate = (key: LoadErrorKey) => string;

/**
 * The text a screen shows when its data failed to load.
 *
 * A request that never reached the server (status 0: no signal, DNS or TLS
 * failure, timeout) gets a plain "check your internet" line instead of the raw
 * "Network request failed", which drivers read as the app being broken.
 */
export function loadErrorMessage(e: unknown, t: Translate): string {
  if (e instanceof ApiError && e.status === 0) return t('common.networkError');
  if (e instanceof Error && e.message) return e.message;
  return t('common.error');
}
