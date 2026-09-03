import { api } from '@/lib/api';

/**
 * How many units of each currency one US dollar buys.
 *
 * `null` means unset, and the country-expense report then shows native amounts
 * only and says the USD column is unavailable — deliberately, rather than
 * converting at a rate nobody chose. A trip that recorded its own exchange
 * brings its own rate and ignores these.
 */
export interface OrgSettings {
  usd_to_kzt: number | null;
  usd_to_rub: number | null;
  usd_to_uzs: number | null;
  updated_at: string | null;
}

/** A full replacement: `null` clears a rate, which is a real intent. */
export type OrgSettingsInput = Omit<OrgSettings, 'updated_at'>;

export const orgSettingsApi = {
  get: () => api<OrgSettings>('/api/org/settings'),
  update: (body: OrgSettingsInput) =>
    api<OrgSettings>('/api/org/settings', { method: 'PUT', body }),
};
