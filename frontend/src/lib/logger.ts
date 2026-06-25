/**
 * Tiny shared logger.
 *
 * No-ops in production builds (import.meta.env.PROD) so we don't leak diagnostic
 * detail to end users' consoles, and forwards to the matching console method in
 * development. User-facing error toasts should be handled separately at the call
 * site — this is for developer diagnostics only.
 */
const isProd = import.meta.env.PROD;

export const logger = {
  log: (...args: unknown[]): void => {
    if (!isProd) console.log(...args);
  },
  info: (...args: unknown[]): void => {
    if (!isProd) console.info(...args);
  },
  warn: (...args: unknown[]): void => {
    if (!isProd) console.warn(...args);
  },
  error: (...args: unknown[]): void => {
    if (!isProd) console.error(...args);
  },
};
