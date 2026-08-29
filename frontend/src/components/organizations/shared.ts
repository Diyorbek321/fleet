import { ApiError } from '@/lib/api';

/** Backend minimum for every password field on this screen; mirrored client-side. */
export const MIN_PASSWORD_LENGTH = 8;

/**
 * Surface the server's own message when there is one.
 *
 * The console provisions and deletes paying customers — a generic "something
 * went wrong" would leave the operator believing a company was created when it
 * wasn't, so the API's `detail` always wins over the fallback.
 */
export function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return fallback;
}
