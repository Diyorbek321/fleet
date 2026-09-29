import { api } from '@/lib/api';
import type { AlertKind, AlertSeverity } from '@/lib/ownerAlerts';

/** The panel's bell. Mirrors `app/routers/notifications.py`. */
export interface PanelNotification {
  id: string;
  kind: AlertKind;
  severity: AlertSeverity;
  /** Server-written text, the same line the owner's Telegram chat receives. */
  title: string;
  body: string;
  /** Panel route the alert is about, e.g. `/trips/<id>`. */
  path: string | null;
  created_at: string;
}

export interface NotificationFeed {
  items: PanelNotification[];
  unread_count: number;
  /** Everything newer than this was unread when the feed was fetched. */
  seen_at: string;
}

export const NOTIFICATIONS_KEY = ['notifications'] as const;

export const notificationsApi = {
  feed: () => api<NotificationFeed>('/api/notifications'),
  markSeen: () => api<NotificationFeed>('/api/notifications/seen', { method: 'POST' }),
};
