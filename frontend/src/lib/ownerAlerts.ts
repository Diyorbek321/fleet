import { api } from '@/lib/api';

/**
 * The organization's own Telegram chats — where owner alerts are delivered.
 *
 * Field names stay snake_case, mirroring `app/routers/owner_alerts.py`
 * one-for-one, the same choice `orgSettings.ts` and `countryExpenses.ts` make:
 * a hand-written camelCase adapter over a payload this shape buys nothing but
 * a place for the two definitions to drift apart, and drift here is silent —
 * a renamed field arrives as `undefined` and reads as "nothing muted".
 */

/**
 * What an alert is about, and the unit an owner mutes. Mirrors
 * `app.models.owner_alerts.AlertKind`.
 *
 * `ALERT_KINDS` below fixes the order they are shown in; the enum's own order
 * is not a display order and the panel must not inherit one by accident.
 */
export type AlertKind =
  | 'trip_status'
  | 'trip_delay'
  | 'leakage'
  | 'document_expiry'
  | 'maintenance_overdue'
  | 'cash_mismatch'
  | 'border_queue'
  | 'report_ready'
  | 'briefing';

/** Ordered loudest-consequence-first, so the money alerts sit above the chatter. */
export const ALERT_KINDS: readonly AlertKind[] = [
  'cash_mismatch',
  'leakage',
  'document_expiry',
  'maintenance_overdue',
  'trip_delay',
  'trip_status',
  'border_queue',
  'report_ready',
  'briefing',
];

/** Ordered `info < warning < critical`, matching the backend's SEVERITY_RANK. */
export type AlertSeverity = 'info' | 'warning' | 'critical';

export const ALERT_SEVERITIES: readonly AlertSeverity[] = ['info', 'warning', 'critical'];

export interface TelegramAccount {
  id: string;
  user_id: string | null;
  /** Who this chat is, in the admin's words ("Direktor"). May be unset. */
  label: string | null;
  /** True once the owner has opened the deep link and the webhook stamped a chat id. */
  activated: boolean;
  activated_at: string | null;
  /** False = linked but silenced, by the owner's /stop or by an admin here. */
  is_active: boolean;
  muted_kinds: AlertKind[];
  min_severity: AlertSeverity;
  /**
   * Asia/Tashkent hours between which non-critical alerts wait. Both null means
   * no quiet window at all — deliver at any hour.
   */
  quiet_from_hour: number | null;
  quiet_to_hour: number | null;
  /**
   * Present only while the chat is unactivated. The server stops echoing it
   * afterwards so a live re-binding credential is not sitting in every list
   * response, which is why this is nullable rather than always a string.
   */
  deep_link: string | null;
  created_at: string;
}

/** What `POST /link` returns: a fresh, unactivated row and the link to hand over. */
export interface TelegramLink {
  id: string;
  token: string;
  deep_link: string;
  label: string | null;
}

export interface TelegramLinkInput {
  label?: string | null;
  user_id?: string | null;
}

/**
 * A partial update: omitted fields are left alone, and for the quiet-hour
 * fields an explicit `null` is a real instruction ("tell me at any hour"). The
 * backend reads `model_fields_set`, so sending only what changed is required —
 * not merely an optimization.
 */
export interface TelegramAccountUpdate {
  muted_kinds?: AlertKind[];
  min_severity?: AlertSeverity;
  quiet_from_hour?: number | null;
  quiet_to_hour?: number | null;
  is_active?: boolean;
}

/** `sent: false` means Telegram refused the message, not that nothing was tried. */
export interface TelegramTestResult {
  sent: boolean;
}

export const ownerAlertsApi = {
  list: () => api<TelegramAccount[]>('/api/org/telegram'),
  link: (body: TelegramLinkInput = {}) =>
    api<TelegramLink>('/api/org/telegram/link', { method: 'POST', body }),
  update: (id: string, body: TelegramAccountUpdate) =>
    api<TelegramAccount>(`/api/org/telegram/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => api<void>(`/api/org/telegram/${id}`, { method: 'DELETE' }),
  test: (id: string) =>
    api<TelegramTestResult>(`/api/org/telegram/${id}/test`, { method: 'POST' }),
};

/** The hours a quiet window may start or end at. */
export const HOURS: readonly number[] = Array.from({ length: 24 }, (_, h) => h);

/** "22" reads as an hour; "22:00" reads as a time. The window is whole hours. */
export function formatHour(hour: number): string {
  return `${String(hour).padStart(2, '0')}:00`;
}

/**
 * Turning a quiet window back on needs a window to turn on, and the backend's
 * own column defaults are the answer the owner is least likely to argue with.
 */
export const DEFAULT_QUIET_FROM = 22;
export const DEFAULT_QUIET_TO = 7;
